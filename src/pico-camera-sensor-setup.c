#include "pico-camera-sensor-setup.h"
#include "pico-camera-buffer.h"
#include "pico-camera-isp.h"
#include <errno.h>
#include <stdlib.h>
#include <string.h>

enum { INITIALIZE, MODE, SYNCHRONIZE, STREAM_ON, STREAM_OFF, STAGES };
struct pico_camera_sensor_setup {
    int fd;
    int32_t session, sensor;
    struct {
        struct pico_camera_buffer *command, *packet;
        bool command_in_flight, packet_in_flight;
    } stages[STAGES];
    bool prepared, submitted, quiesced;
};
static const enum pico_camera_packet_opcode opcodes[STAGES] = {
    PICO_CAMERA_PACKET_SENSOR_INITIALIZE, PICO_CAMERA_PACKET_SENSOR_CONFIGURE,
    PICO_CAMERA_PACKET_SENSOR_CONFIGURE, PICO_CAMERA_PACKET_SENSOR_STREAM_ON,
    PICO_CAMERA_PACKET_SENSOR_STREAM_OFF,
};
static int prepare_stage(struct pico_camera_sensor_setup *s, unsigned stage, int crm,
                          const struct pico_camera_sensor_table *table, size_t bytes, bool bus_only)
{
    struct pico_camera_buffer_config c = {.kind = PICO_CAMERA_BUFFER_COMMAND,
        .mapping = PICO_CAMERA_MEMORY_CPU, .size = (bytes + 4095) & ~(size_t)4095, .cached = true};
    int result = pico_camera_buffer_create(crm, -1, &c, &s->stages[stage].command);
    if (result) return result;
    c.kind = PICO_CAMERA_BUFFER_PACKET; c.size = 4096;
    result = pico_camera_buffer_create(crm, -1, &c, &s->stages[stage].packet);
    if (result) return result;
    struct pico_camera_buffer_view command, packet;
    if (!pico_camera_buffer_view(s->stages[stage].command, &command) ||
        !pico_camera_buffer_view(s->stages[stage].packet, &packet)) return -EINVAL;
    result = pico_camera_buffer_cpu_begin(s->stages[stage].command, ION_BUFFER_WRITE);
    if (result) return result;
    memset(command.data, 0, command.size);
    size_t encoded;
    if (bus_only) {
        uint8_t *data = command.data;
        for (unsigned i = 0; i < 4; ++i) data[i] = (uint8_t)(table->bus.slave_address >> (8 * i));
        data[4] = (uint8_t)table->bus.frequency; data[5] = 4;
        encoded = 8;
    } else encoded = pico_camera_sensor_writes(&table->bus, table->writes, table->count, command.data, command.size);
    result = pico_camera_buffer_cpu_end(s->stages[stage].command);
    if (result || encoded != bytes) return result ? result : -EINVAL;
    struct pico_camera_command_buffer reference = {.memory_handle = command.memory_handle,
        .capacity = (uint32_t)command.size, .length = (uint32_t)bytes, .type = 7,
        .allocation_size = command.size};
    struct pico_camera_packet_config config = {.opcode = opcodes[stage], .commands = &reference,
        .command_count = 1, .kernel_command_index = -1};
    result = pico_camera_buffer_cpu_begin(s->stages[stage].packet, ION_BUFFER_WRITE);
    if (result) return result;
    memset(packet.data, 0, packet.size);
    encoded = pico_camera_packet_encode(&config, packet.data, packet.size);
    result = pico_camera_buffer_cpu_end(s->stages[stage].packet);
    return result ? result : encoded ? 0 : -EINVAL;
}
int pico_camera_sensor_setup_prepare(const struct pico_camera_sensor_setup_config *c,
                                     struct pico_camera_sensor_setup **setup)
{
    if (!c || !setup || *setup || c->crm_fd < 0 || c->sensor_fd < 0 || c->session <= 0 || c->sensor <= 0)
        return -EINVAL;
    const struct pico_camera_sensor_table *tables[STAGES] = {
        &c->initialize, &c->mode, &c->synchronize, &c->stream_on, &c->stream_off,
    };
    size_t sizes[STAGES] = {0};
    for (unsigned i = 0; i < STAGES; ++i) {
        if (c->mcu_controlled) {
            if (tables[i]->count || tables[i]->writes) return -EINVAL;
            continue;
        }
        if (i == SYNCHRONIZE && !tables[i]->count) continue;
        sizes[i] = pico_camera_sensor_writes_size(&tables[i]->bus, tables[i]->writes, tables[i]->count);
        if (!sizes[i]) return -EINVAL;
    }
    if (c->mcu_controlled) {
        const struct pico_camera_sensor_bus *bus = &c->mode.bus;
        if (!bus->slave_address || bus->slave_address > 254 || (bus->slave_address & 1) || bus->frequency > 3)
            return -EINVAL;
        /* The kernel discards NOP requests in ACQUIRE, even with MCU-owned sensors. */
        sizes[MODE] = 8;
    }
    struct pico_camera_sensor_setup *s = calloc(1, sizeof(*s));
    if (!s) return -ENOMEM;
    *setup = s; s->fd = c->sensor_fd; s->session = c->session; s->sensor = c->sensor;
    for (unsigned i = 0; i < STAGES; ++i) {
        if (!sizes[i]) continue;
        int result = prepare_stage(s, i, c->crm_fd, tables[i], sizes[i], c->mcu_controlled);
        if (result) return result;
    }
    s->prepared = true;
    return 0;
}
int pico_camera_sensor_setup_submit(struct pico_camera_sensor_setup *s)
{
    if (!s || !s->prepared || s->submitted) return -EINVAL;
    s->submitted = true;
    for (unsigned i = 0; i < STAGES; ++i) {
        if (!s->stages[i].packet) continue;
        struct pico_camera_buffer_view packet;
        if (!pico_camera_buffer_view(s->stages[i].packet, &packet)) return -EINVAL;
        int result = pico_camera_buffer_submit(s->stages[i].command);
        if (result) return result;
        s->stages[i].command_in_flight = true;
        result = pico_camera_buffer_submit(s->stages[i].packet);
        if (result) return result;
        s->stages[i].packet_in_flight = true;
        result = pico_camera_device_configure(s->fd, s->session, s->sensor,
            packet.memory_handle, 0, packet.size);
        if (result) return result;
    }
    return 0;
}
int pico_camera_sensor_setup_quiesced(struct pico_camera_sensor_setup *s)
{
    if (!s || !s->submitted || s->quiesced) return -EINVAL;
    for (unsigned i = 0; i < STAGES; ++i) {
        if (s->stages[i].command_in_flight) {
            int result = pico_camera_buffer_complete(s->stages[i].command);
            if (result) return result;
            s->stages[i].command_in_flight = false;
        }
        if (s->stages[i].packet_in_flight) {
            int result = pico_camera_buffer_complete(s->stages[i].packet);
            if (result) return result;
            s->stages[i].packet_in_flight = false;
        }
    }
    s->quiesced = true;
    return 0;
}
int pico_camera_sensor_setup_release(struct pico_camera_sensor_setup **setup)
{
    if (!setup) return -EINVAL;
    struct pico_camera_sensor_setup *s = *setup;
    if (!s) return 0;
    if (s->submitted && !s->quiesced) return -EBUSY;
    s->prepared = false;
    for (unsigned i = 0; i < STAGES; ++i) {
        int result = pico_camera_buffer_release(&s->stages[i].packet);
        if (!result) result = pico_camera_buffer_release(&s->stages[i].command);
        if (result) return result;
    }
    free(s); *setup = NULL;
    return 0;
}
