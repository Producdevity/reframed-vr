from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT/'tests/fixtures/pico-bluetooth-address'
PATCH = ROOT/'patches/kernel/pico-neo3/experimental/0055-qca-public-address-byte-order.patch'

HARNESS = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef unsigned char u8;
typedef struct {u8 b[6];} bdaddr_t;
struct hci_dev {int unused;};
struct sk_buff {int unused;};
#define EDL_WRITE_BD_ADDR_OPCODE 0xfc14
#define EDL_NVM_ACCESS_OPCODE 0xfc0b
#define EDL_NVM_ACCESS_SET_REQ_CMD 1
#define HCI_EV_VENDOR 255
#define HCI_INIT_TIMEOUT 1000
#define IS_ERR(p) ((uintptr_t)(p)>=(uintptr_t)-4095)
#define PTR_ERR(p) ((int)(intptr_t)(p))
#define bt_dev_err(...) ((void)0)
static unsigned opcode,size,event,frees,fail;
static u8 payload[9];
void baswap(bdaddr_t *to,const bdaddr_t *from){for(unsigned i=0;i<6;++i)to->b[i]=from->b[5-i];}
static struct sk_buff * __hci_cmd_sync_ev(struct hci_dev *dev,unsigned op,unsigned len,const void *data,unsigned ev,unsigned timeout){
 static struct sk_buff skb;(void)dev;assert(timeout==HCI_INIT_TIMEOUT&&len<=sizeof(payload));
 opcode=op;size=len;event=ev;memcpy(payload,data,len);return fail?(void *)(intptr_t)-5:&skb;
}
static void kfree_skb(struct sk_buff *skb){assert(skb&&!IS_ERR(skb));++frees;}
#include "drivers/bluetooth/btqca.c"
int main(int argc,char **argv){
 struct hci_dev dev={0};bdaddr_t address={{0x90,0x78,0x56,0x34,0x12,0xa0}};
 int legacy=argc==2&&!strcmp(argv[1],"rome");
 assert(!(legacy?qca_set_bdaddr_rome(&dev,&address):qca_set_bdaddr(&dev,&address)));
 assert(event==HCI_EV_VENDOR&&frees==1);
 if(legacy){assert(opcode==EDL_NVM_ACCESS_OPCODE&&size==9);assert(payload[0]==1&&payload[1]==2&&payload[2]==6);assert(!memcmp(payload+3,address.b,6));}
 else{const u8 expected[]={0xa0,0x12,0x34,0x56,0x78,0x90};assert(opcode==EDL_WRITE_BD_ADDR_OPCODE&&size==6);assert(!memcmp(payload,expected,6));}
 fail=1;assert((legacy?qca_set_bdaddr_rome(&dev,&address):qca_set_bdaddr(&dev,&address))==-5);assert(frees==1);
 puts("QCA_ADDRESS_WIRE_ORACLE_PASS");return 0;
}
'''


class PicoBluetoothAddressPatchTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc') and shutil.which('patch'), 'C compiler and patch required')
    def test_actual_callbacks_keep_rome_order_and_fix_qca_wire_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            shutil.copytree(FIXTURE, root, dirs_exist_ok=True)
            (root/'test.c').write_text(HARNESS)
            before = (root/'drivers/bluetooth/btqca.c').read_text()

            def compile(name):
                subprocess.run(['cc','-std=c11','-O1','-g','-Wall','-Wextra','-Werror',
                                '-fsanitize=address,undefined',str(root/'test.c'),'-o',str(root/name)],
                               check=True,capture_output=True,text=True,timeout=30)

            compile('before')
            subprocess.run([str(root/'before'),'rome'],check=True,capture_output=True,timeout=10)
            original = subprocess.run([str(root/'before')],capture_output=True,text=True,timeout=10)
            self.assertNotEqual(original.returncode,0)
            self.assertIn('memcmp(payload,expected,6)',original.stderr.replace(' ',''))
            subprocess.run(['patch','--batch','--fuzz=0','--forward','-p1','-i',str(PATCH)],
                           cwd=root,check=True,capture_output=True,text=True,timeout=10)
            after = (root/'drivers/bluetooth/btqca.c').read_text()
            self.assertEqual(before.split('int qca_set_bdaddr(')[0],after.split('int qca_set_bdaddr(')[0])
            compile('after')
            for args in [[],['rome']]:
                result = subprocess.run([str(root/'after'),*args],check=True,capture_output=True,text=True,timeout=10)
                self.assertIn('QCA_ADDRESS_WIRE_ORACLE_PASS',result.stdout)


if __name__ == '__main__':
    unittest.main()
