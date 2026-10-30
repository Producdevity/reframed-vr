/* SPDX-License-Identifier: GPL-2.0-only */
/* Copyright (C) 2014 Intel Corporation */
/* Request builders extracted from the retained Neo3 4.19.81 hci_request.c,
 * SHA256 629d106c6e8707085200db8072c70a6583492ec5336be773c7d02e1cc309defc.
 * The fixture records HCI commands and stubs unrelated address/permission work.
 * Upstream correction: 492ad783a150cd352abba8723e5942521d938c8d.
 */

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
typedef uint8_t u8;
typedef uint32_t u32;
typedef uint8_t __u8;
typedef uint16_t __le16;
typedef struct { u8 b[6]; } bdaddr_t;
#define __packed __attribute__((packed))
#define HCI_MAX_AD_LENGTH 31
#define HCI_MAX_SHORT_NAME_LENGTH 10
#define EIR_NAME_SHORT 0x08
#define EIR_NAME_COMPLETE 0x09
#define EIR_APPEARANCE 0x19
#define cpu_to_le16(x) (x)
#define MGMT_ADV_FLAG_CONNECTABLE (1 << 0)
#define MGMT_ADV_FLAG_TX_POWER (1 << 1)
#define MGMT_ADV_FLAG_MANAGED_FLAGS (1 << 2)
#define MGMT_ADV_FLAG_LIMITED_DISCOV (1 << 3)
#define MGMT_ADV_FLAG_DISCOV (1 << 4)
#define MGMT_ADV_FLAG_APPEARANCE (1 << 5)
#define MGMT_ADV_FLAG_LOCAL_NAME (1 << 6)
#define MGMT_ADV_FLAG_SEC_2M (1 << 7)
#define MGMT_ADV_FLAG_SEC_CODED (1 << 8)
#define MGMT_ADV_FLAG_SEC_MASK (MGMT_ADV_FLAG_SEC_2M | MGMT_ADV_FLAG_SEC_CODED)
enum { HCI_LE_ENABLED, HCI_ADVERTISING_CONNECTABLE, HCI_LIMITED_DISCOVERABLE, HCI_DISCOVERABLE };
struct adv_info { u8 instance; u32 flags; u8 scan_rsp_len; u8 scan_rsp_data[31]; bdaddr_t random_addr; };
struct hci_dev {
    u8 cur_adv_instance, le_adv_channel_map, scan_rsp_data_len;
    u8 scan_rsp_data[31];
    char dev_name[249], short_name[11];
    uint16_t appearance;
    u32 flags;
    bool extended, connectable;
    struct adv_info adv;
    bdaddr_t random_addr;
};
struct command { uint16_t opcode; u8 length; u8 data[64]; };
struct hci_request { struct hci_dev *hdev; int count; struct command commands[8]; };
static const bdaddr_t zero_address = {{0}};
#define BDADDR_ANY (&zero_address)
static int bacmp(const bdaddr_t *a, const bdaddr_t *b) { return memcmp(a, b, sizeof(*a)); }
static void bacpy(bdaddr_t *a, const bdaddr_t *b) { memcpy(a, b, sizeof(*a)); }
static struct adv_info *hci_find_adv_instance(struct hci_dev *h, u8 i) { return i && i == h->adv.instance ? &h->adv : NULL; }
static bool hci_dev_test_flag(struct hci_dev *h, unsigned f) { return !!(h->flags & (1U << f)); }
static bool ext_adv_capable(struct hci_dev *h) { return h->extended; }
static bool mgmt_get_connectable(struct hci_dev *h) { return h->connectable; }
static bool is_advertising_allowed(struct hci_dev *h, bool c) { (void)h; (void)c; return true; }
static bool adv_use_rpa(struct hci_dev *h, u32 f) { (void)h; (void)f; return false; }
static int hci_get_random_address(struct hci_dev *h, bool privacy, bool rpa, struct adv_info *a, u8 *type, bdaddr_t *address) {
    (void)h; (void)privacy; (void)rpa; (void)a; *type = 0; *address = zero_address; return 0;
}
static u8 eir_append_data(u8 *data, u8 offset, u8 type, const void *payload, u8 length) {
    assert(offset + length + 2 <= 31); data[offset] = length + 1; data[offset+1] = type;
    memcpy(data + offset + 2, payload, length); return offset + length + 2;
}
static u8 eir_append_le16(u8 *data, u8 offset, u8 type, uint16_t value) {
    u8 bytes[2] = {value & 255, value >> 8}; return eir_append_data(data, offset, type, bytes, 2);
}
static void hci_req_add(struct hci_request *r, uint16_t opcode, u8 size, const void *data) {
    assert(r->count < 8 && size <= 64); struct command *c = &r->commands[r->count++];
    c->opcode = opcode; c->length = size; memcpy(c->data, data, size);
}
#define HCI_OP_LE_SET_EXT_ADV_PARAMS		0x2036
#define HCI_ADV_PHY_1M		0X01
#define HCI_ADV_PHY_2M		0x02
#define HCI_ADV_PHY_CODED	0x03
#define HCI_OP_LE_SET_EXT_SCAN_RSP_DATA		0x2038
#define LE_SET_ADV_DATA_OP_COMPLETE	0x03
#define LE_SET_ADV_DATA_NO_FRAG		0x01
#define HCI_OP_LE_SET_ADV_SET_RAND_ADDR	0x2035
#define HCI_OP_LE_SET_SCAN_RSP_DATA	0x2009
#define LE_LEGACY_ADV_IND		0x0013
#define LE_LEGACY_ADV_SCAN_IND		0x0012
#define LE_LEGACY_NONCONN_IND		0x0010
#define LE_EXT_ADV_NON_CONN_IND		0x0000
#define LE_EXT_ADV_CONN_IND		0x0001
#define LE_EXT_ADV_SCAN_IND		0x0002
#define ADDR_LE_DEV_PUBLIC	0x00
#define ADDR_LE_DEV_RANDOM	0x01
struct hci_cp_le_set_ext_adv_params {
	__u8      handle;
	__le16    evt_properties;
	__u8      min_interval[3];
	__u8      max_interval[3];
	__u8      channel_map;
	__u8      own_addr_type;
	__u8      peer_addr_type;
	bdaddr_t  peer_addr;
	__u8      filter_policy;
	__u8      tx_power;
	__u8      primary_phy;
	__u8      secondary_max_skip;
	__u8      secondary_phy;
	__u8      sid;
	__u8      notif_enable;
} __packed;
struct hci_cp_le_set_ext_scan_rsp_data {
	__u8  handle;
	__u8  operation;
	__u8  frag_pref;
	__u8  length;
	__u8  data[HCI_MAX_AD_LENGTH];
} __packed;
struct hci_cp_le_set_adv_set_rand_addr {
	__u8  handle;
	bdaddr_t  bdaddr;
} __packed;
struct hci_cp_le_set_scan_rsp_data {
	__u8	length;
	__u8	data[HCI_MAX_AD_LENGTH];
} __packed;
static u8 get_adv_instance_scan_rsp_len(struct hci_dev *hdev, u8 instance)
{
	struct adv_info *adv_instance;

	/* Ignore instance 0 */
	if (instance == 0x00)
		return 0;

	adv_instance = hci_find_adv_instance(hdev, instance);
	if (!adv_instance)
		return 0;

	/* TODO: Take into account the "appearance" and "local-name" flags here.
	 * These are currently being ignored as they are not supported.
	 */
	return adv_instance->scan_rsp_len;
}

static u8 get_cur_adv_instance_scan_rsp_len(struct hci_dev *hdev)
{
	u8 instance = hdev->cur_adv_instance;
	struct adv_info *adv_instance;

	/* Ignore instance 0 */
	if (instance == 0x00)
		return 0;

	adv_instance = hci_find_adv_instance(hdev, instance);
	if (!adv_instance)
		return 0;

	/* TODO: Take into account the "appearance" and "local-name" flags here.
	 * These are currently being ignored as they are not supported.
	 */
	return adv_instance->scan_rsp_len;
}

static u32 get_adv_instance_flags(struct hci_dev *hdev, u8 instance)
{
	u32 flags;
	struct adv_info *adv_instance;

	if (instance == 0x00) {
		/* Instance 0 always manages the "Tx Power" and "Flags"
		 * fields
		 */
		flags = MGMT_ADV_FLAG_TX_POWER | MGMT_ADV_FLAG_MANAGED_FLAGS;

		/* For instance 0, the HCI_ADVERTISING_CONNECTABLE setting
		 * corresponds to the "connectable" instance flag.
		 */
		if (hci_dev_test_flag(hdev, HCI_ADVERTISING_CONNECTABLE))
			flags |= MGMT_ADV_FLAG_CONNECTABLE;

		if (hci_dev_test_flag(hdev, HCI_LIMITED_DISCOVERABLE))
			flags |= MGMT_ADV_FLAG_LIMITED_DISCOV;
		else if (hci_dev_test_flag(hdev, HCI_DISCOVERABLE))
			flags |= MGMT_ADV_FLAG_DISCOV;

		return flags;
	}

	adv_instance = hci_find_adv_instance(hdev, instance);

	/* Return 0 when we got an invalid instance identifier. */
	if (!adv_instance)
		return 0;

	return adv_instance->flags;
}

u8 append_local_name(struct hci_dev *hdev, u8 *ptr, u8 ad_len)
{
	size_t short_len;
	size_t complete_len;

	/* no space left for name (+ NULL + type + len) */
	if ((HCI_MAX_AD_LENGTH - ad_len) < HCI_MAX_SHORT_NAME_LENGTH + 3)
		return ad_len;

	/* use complete name if present and fits */
	complete_len = strlen(hdev->dev_name);
	if (complete_len && complete_len <= HCI_MAX_SHORT_NAME_LENGTH)
		return eir_append_data(ptr, ad_len, EIR_NAME_COMPLETE,
				       hdev->dev_name, complete_len + 1);

	/* use short name if present */
	short_len = strlen(hdev->short_name);
	if (short_len)
		return eir_append_data(ptr, ad_len, EIR_NAME_SHORT,
				       hdev->short_name, short_len + 1);

	/* use shortened full name if present, we already know that name
	 * is longer then HCI_MAX_SHORT_NAME_LENGTH
	 */
	if (complete_len) {
		u8 name[HCI_MAX_SHORT_NAME_LENGTH + 1];

		memcpy(name, hdev->dev_name, HCI_MAX_SHORT_NAME_LENGTH);
		name[HCI_MAX_SHORT_NAME_LENGTH] = '\0';

		return eir_append_data(ptr, ad_len, EIR_NAME_SHORT, name,
				       sizeof(name));
	}

	return ad_len;
}

static u8 append_appearance(struct hci_dev *hdev, u8 *ptr, u8 ad_len)
{
	return eir_append_le16(ptr, ad_len, EIR_APPEARANCE, hdev->appearance);
}

static u8 create_default_scan_rsp_data(struct hci_dev *hdev, u8 *ptr)
{
	u8 scan_rsp_len = 0;

	if (hdev->appearance) {
		scan_rsp_len = append_appearance(hdev, ptr, scan_rsp_len);
	}

	return append_local_name(hdev, ptr, scan_rsp_len);
}

static u8 create_instance_scan_rsp_data(struct hci_dev *hdev, u8 instance,
					u8 *ptr)
{
	struct adv_info *adv_instance;
	u32 instance_flags;
	u8 scan_rsp_len = 0;

	adv_instance = hci_find_adv_instance(hdev, instance);
	if (!adv_instance)
		return 0;

	instance_flags = adv_instance->flags;

	if ((instance_flags & MGMT_ADV_FLAG_APPEARANCE) && hdev->appearance) {
		scan_rsp_len = append_appearance(hdev, ptr, scan_rsp_len);
	}

	memcpy(&ptr[scan_rsp_len], adv_instance->scan_rsp_data,
	       adv_instance->scan_rsp_len);

	scan_rsp_len += adv_instance->scan_rsp_len;

	if (instance_flags & MGMT_ADV_FLAG_LOCAL_NAME)
		scan_rsp_len = append_local_name(hdev, ptr, scan_rsp_len);

	return scan_rsp_len;
}

void __hci_req_update_scan_rsp_data(struct hci_request *req, u8 instance)
{
	struct hci_dev *hdev = req->hdev;
	u8 len;

	if (!hci_dev_test_flag(hdev, HCI_LE_ENABLED))
		return;

	if (ext_adv_capable(hdev)) {
		struct hci_cp_le_set_ext_scan_rsp_data cp;

		memset(&cp, 0, sizeof(cp));

		if (instance)
			len = create_instance_scan_rsp_data(hdev, instance,
							    cp.data);
		else
			len = create_default_scan_rsp_data(hdev, cp.data);

		if (hdev->scan_rsp_data_len == len &&
		    !memcmp(cp.data, hdev->scan_rsp_data, len))
			return;

		memcpy(hdev->scan_rsp_data, cp.data, sizeof(cp.data));
		hdev->scan_rsp_data_len = len;

		cp.handle = 0;
		cp.length = len;
		cp.operation = LE_SET_ADV_DATA_OP_COMPLETE;
		cp.frag_pref = LE_SET_ADV_DATA_NO_FRAG;

		hci_req_add(req, HCI_OP_LE_SET_EXT_SCAN_RSP_DATA, sizeof(cp),
			    &cp);
	} else {
		struct hci_cp_le_set_scan_rsp_data cp;

		memset(&cp, 0, sizeof(cp));

		if (instance)
			len = create_instance_scan_rsp_data(hdev, instance,
							    cp.data);
		else
			len = create_default_scan_rsp_data(hdev, cp.data);

		if (hdev->scan_rsp_data_len == len &&
		    !memcmp(cp.data, hdev->scan_rsp_data, len))
			return;

		memcpy(hdev->scan_rsp_data, cp.data, sizeof(cp.data));
		hdev->scan_rsp_data_len = len;

		cp.length = len;

		hci_req_add(req, HCI_OP_LE_SET_SCAN_RSP_DATA, sizeof(cp), &cp);
	}
}

int __hci_req_setup_ext_adv_instance(struct hci_request *req, u8 instance)
{
	struct hci_cp_le_set_ext_adv_params cp;
	struct hci_dev *hdev = req->hdev;
	bool connectable;
	u32 flags;
	bdaddr_t random_addr;
	u8 own_addr_type;
	int err;
	struct adv_info *adv_instance;
	bool secondary_adv;
	/* In ext adv set param interval is 3 octets */
	const u8 adv_interval[3] = { 0x00, 0x08, 0x00 };

	if (instance > 0) {
		adv_instance = hci_find_adv_instance(hdev, instance);
		if (!adv_instance)
			return -EINVAL;
	} else {
		adv_instance = NULL;
	}

	flags = get_adv_instance_flags(hdev, instance);

	/* If the "connectable" instance flag was not set, then choose between
	 * ADV_IND and ADV_NONCONN_IND based on the global connectable setting.
	 */
	connectable = (flags & MGMT_ADV_FLAG_CONNECTABLE) ||
		      mgmt_get_connectable(hdev);

	 if (!is_advertising_allowed(hdev, connectable))
		return -EPERM;

	/* Set require_privacy to true only when non-connectable
	 * advertising is used. In that case it is fine to use a
	 * non-resolvable private address.
	 */
	err = hci_get_random_address(hdev, !connectable,
				     adv_use_rpa(hdev, flags), adv_instance,
				     &own_addr_type, &random_addr);
	if (err < 0)
		return err;

	memset(&cp, 0, sizeof(cp));

	memcpy(cp.min_interval, adv_interval, sizeof(cp.min_interval));
	memcpy(cp.max_interval, adv_interval, sizeof(cp.max_interval));

	secondary_adv = (flags & MGMT_ADV_FLAG_SEC_MASK);

	if (connectable) {
		if (secondary_adv)
			cp.evt_properties = cpu_to_le16(LE_EXT_ADV_CONN_IND);
		else
			cp.evt_properties = cpu_to_le16(LE_LEGACY_ADV_IND);
	} else if (get_adv_instance_scan_rsp_len(hdev, instance)) {
		if (secondary_adv)
			cp.evt_properties = cpu_to_le16(LE_EXT_ADV_SCAN_IND);
		else
			cp.evt_properties = cpu_to_le16(LE_LEGACY_ADV_SCAN_IND);
	} else {
		if (secondary_adv)
			cp.evt_properties = cpu_to_le16(LE_EXT_ADV_NON_CONN_IND);
		else
			cp.evt_properties = cpu_to_le16(LE_LEGACY_NONCONN_IND);
	}

	cp.own_addr_type = own_addr_type;
	cp.channel_map = hdev->le_adv_channel_map;
	cp.tx_power = 127;
	cp.handle = 0;

	if (flags & MGMT_ADV_FLAG_SEC_2M) {
		cp.primary_phy = HCI_ADV_PHY_1M;
		cp.secondary_phy = HCI_ADV_PHY_2M;
	} else if (flags & MGMT_ADV_FLAG_SEC_CODED) {
		cp.primary_phy = HCI_ADV_PHY_CODED;
		cp.secondary_phy = HCI_ADV_PHY_CODED;
	} else {
		/* In all other cases use 1M */
		cp.primary_phy = HCI_ADV_PHY_1M;
		cp.secondary_phy = HCI_ADV_PHY_1M;
	}

	hci_req_add(req, HCI_OP_LE_SET_EXT_ADV_PARAMS, sizeof(cp), &cp);

	if (own_addr_type == ADDR_LE_DEV_RANDOM &&
	    bacmp(&random_addr, BDADDR_ANY)) {
		struct hci_cp_le_set_adv_set_rand_addr cp;

		/* Check if random address need to be updated */
		if (adv_instance) {
			if (!bacmp(&random_addr, &adv_instance->random_addr))
				return 0;
		} else {
			if (!bacmp(&random_addr, &hdev->random_addr))
				return 0;
		}

		memset(&cp, 0, sizeof(cp));

		cp.handle = 0;
		bacpy(&cp.bdaddr, &random_addr);

		hci_req_add(req,
			    HCI_OP_LE_SET_ADV_SET_RAND_ADDR,
			    sizeof(cp), &cp);
	}

	return 0;
}

static struct hci_dev initial(void) {
    struct hci_dev h = {.flags = 1U << HCI_LE_ENABLED, .extended = true, .le_adv_channel_map = 7};
    strcpy(h.dev_name, "reframed-vr"); return h;
}
int main(int argc, char **argv) {
    assert(argc == 2); bool patched = atoi(argv[1]);
    struct hci_dev h = initial(); struct hci_request r = {.hdev = &h};
    assert(!!get_adv_instance_scan_rsp_len(&h, 0) == patched);
    assert(!!get_cur_adv_instance_scan_rsp_len(&h) == patched);
    assert(__hci_req_setup_ext_adv_instance(&r, 0) == 0);
    __hci_req_update_scan_rsp_data(&r, 0);
    assert(r.count == 2);
    assert(r.commands[0].opcode == 0x2036 && r.commands[0].length == 25);
    assert(r.commands[1].opcode == 0x2038 && r.commands[1].length == 35);
    const struct hci_cp_le_set_ext_adv_params *params = (const void *)r.commands[0].data;
    const struct hci_cp_le_set_ext_scan_rsp_data *scan = (const void *)r.commands[1].data;
    assert(params->evt_properties == (patched ? 0x12 : 0x10));
    assert(scan->length == 13 && scan->operation == 3 && scan->frag_pref == 1);
    int spec_status = !(params->evt_properties & 2) && scan->length ? 0x12 : 0;
    assert(spec_status == (patched ? 0 : 0x12));
    printf("{\"default_properties\":%u,\"default_scan_response_hex\":\"", params->evt_properties);
    for (int i=0; i<35; i++) printf("%02x", r.commands[1].data[i]);
    printf("\",\"mode_rule_status\":%d,", spec_status);
    __hci_req_update_scan_rsp_data(&r, 0); assert(r.count == 2);

    h = initial(); h.connectable = true; r = (struct hci_request){.hdev=&h};
    assert(!__hci_req_setup_ext_adv_instance(&r, 0));
    params = (const void *)r.commands[0].data; assert(params->evt_properties == 0x13);
    h = initial(); h.adv.instance=1; h.adv.scan_rsp_len=3;
    memcpy(h.adv.scan_rsp_data, "\x02\xff\xaa", 3); h.cur_adv_instance=1;
    assert(get_adv_instance_scan_rsp_len(&h,1)==3 && get_cur_adv_instance_scan_rsp_len(&h)==3);
    r = (struct hci_request){.hdev=&h}; assert(!__hci_req_setup_ext_adv_instance(&r,1));
    __hci_req_update_scan_rsp_data(&r,1); assert(r.count==2);
    params=(const void *)r.commands[0].data; scan=(const void *)r.commands[1].data;
    assert(params->evt_properties==0x12 && scan->length==3 && !memcmp(scan->data,"\x02\xff\xaa",3));
    h.adv.scan_rsp_len=0; h.scan_rsp_data_len=0; r=(struct hci_request){.hdev=&h};
    assert(!__hci_req_setup_ext_adv_instance(&r,1)); __hci_req_update_scan_rsp_data(&r,1);
    params=(const void *)r.commands[0].data; assert(r.count==1 && params->evt_properties==0x10);
    r=(struct hci_request){.hdev=&h}; assert(__hci_req_setup_ext_adv_instance(&r,2)==-EINVAL && !r.count);
    h=initial(); h.extended=false; r=(struct hci_request){.hdev=&h};
    __hci_req_update_scan_rsp_data(&r,0);
    assert(r.count==1 && r.commands[0].opcode==HCI_OP_LE_SET_SCAN_RSP_DATA && r.commands[0].data[0]==13);
    h=initial(); h.flags=0; r=(struct hci_request){.hdev=&h};
    __hci_req_update_scan_rsp_data(&r,0); assert(!r.count);
    puts("\"scenarios\":8,\"passed\":true}");
}
