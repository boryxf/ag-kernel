/**
 * ag-kernel Custom Binary Tick Format Implementation
 *
 * See agtick.h for format specification.
 */

#include "agtick.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>

/* Platform-specific includes for mmap */
#ifdef _WIN32
    #include <windows.h>
    #include <io.h>
#else
    #include <sys/mman.h>
    #include <sys/stat.h>
    #include <fcntl.h>
    #include <unistd.h>
#endif

/* ========== Mmap Handle Structure ========== */

struct agtick_mmap_handle_s {
    void*           data;           /* Mapped data pointer */
    size_t          size;           /* Total mapped size */
    agtick_header_t header;         /* Copied header */
    const uint8_t*  tick_data;      /* Pointer to tick data section */
    const uint8_t*  side_data;      /* Pointer to side bits section */
    size_t          tick_data_len;  /* Length of tick data */

    /* Iterator state */
    const uint8_t*  iter_pos;       /* Current position in tick data */
    size_t          iter_side_idx;  /* Current side bit index */
    int64_t         prev_ts;        /* Previous timestamp for delta decoding */
    int64_t         prev_price;     /* Previous price for delta decoding */
    uint64_t        ticks_read;     /* Number of ticks decoded */

#ifdef _WIN32
    HANDLE          file_handle;    /* Windows file handle */
    HANDLE          map_handle;     /* Windows mapping handle */
#else
    int             fd;             /* Unix file descriptor */
#endif
};

/* ========== Varint Encoding/Decoding ========== */

int agtick_encode_varint(uint64_t value, uint8_t* buf)
{
    int n = 0;
    while (value >= 0x80) {
        buf[n++] = (uint8_t)(value | 0x80);
        value >>= 7;
    }
    buf[n++] = (uint8_t)value;
    return n;
}

int agtick_decode_varint(const uint8_t* buf, size_t buf_len, uint64_t* value_out)
{
    uint64_t result = 0;
    int shift = 0;
    size_t i = 0;

    while (i < buf_len) {
        uint8_t byte = buf[i++];
        result |= ((uint64_t)(byte & 0x7F)) << shift;
        if ((byte & 0x80) == 0) {
            *value_out = result;
            return (int)i;
        }
        shift += 7;
        if (shift >= 64) {
            return AGTICK_ERR_CORRUPT;
        }
    }
    return AGTICK_ERR_CORRUPT;
}

int agtick_encode_svarint(int64_t value, uint8_t* buf)
{
    /* ZigZag encoding: map signed to unsigned */
    uint64_t encoded = ((uint64_t)value << 1) ^ (uint64_t)(value >> 63);
    return agtick_encode_varint(encoded, buf);
}

int agtick_decode_svarint(const uint8_t* buf, size_t buf_len, int64_t* value_out)
{
    uint64_t encoded;
    int n = agtick_decode_varint(buf, buf_len, &encoded);
    if (n < 0) return n;

    /* ZigZag decoding */
    *value_out = (int64_t)((encoded >> 1) ^ -(int64_t)(encoded & 1));
    return n;
}

/* ========== Error Messages ========== */

const char* agtick_strerror(int err)
{
    switch (err) {
        case AGTICK_OK:         return "Success";
        case AGTICK_ERR_IO:     return "I/O error";
        case AGTICK_ERR_MAGIC:  return "Invalid magic bytes (not an agtick file)";
        case AGTICK_ERR_VERSION: return "Unsupported format version";
        case AGTICK_ERR_CORRUPT: return "Corrupted data";
        case AGTICK_ERR_NOMEM:  return "Out of memory";
        case AGTICK_ERR_PARAM:  return "Invalid parameter";
        case AGTICK_ERR_MMAP:   return "Memory mapping failed";
        default:                return "Unknown error";
    }
}

/* ========== Writing Functions ========== */

/**
 * Calculate the maximum buffer size needed for encoding.
 * Worst case: 10 bytes per varint field x 3 fields = 30 bytes per tick.
 */
static size_t calc_max_encoded_size(uint64_t count)
{
    size_t tick_data = count * 30;           /* 3 varints per tick (max 10 bytes each) */
    size_t side_data = (count + 7) / 8;      /* 1 bit per tick, rounded up */
    return tick_data + side_data;
}

int agtick_write(const char* path,
                 const tick_event_t* ticks,
                 uint64_t count,
                 const char* symbol,
                 double tick_size)
{
    FILE* fp = NULL;
    uint8_t* buffer = NULL;
    uint8_t* side_buffer = NULL;
    int result = AGTICK_OK;

    /* Validate parameters */
    if (!path || (!ticks && count > 0) || !symbol) {
        return AGTICK_ERR_PARAM;
    }

    /* Open file for writing */
    fp = fopen(path, "wb");
    if (!fp) {
        return AGTICK_ERR_IO;
    }

    /* Allocate encoding buffers */
    size_t max_size = calc_max_encoded_size(count);
    buffer = (uint8_t*)malloc(max_size);
    side_buffer = (uint8_t*)calloc((count + 7) / 8, 1);

    if (!buffer || !side_buffer) {
        result = AGTICK_ERR_NOMEM;
        goto cleanup;
    }

    /* Encode tick data with delta encoding */
    size_t buf_pos = 0;
    int64_t prev_ts = 0;
    int64_t prev_price = 0;

    for (uint64_t i = 0; i < count; i++) {
        const tick_event_t* t = &ticks[i];

        /* Delta-encode timestamp */
        int64_t ts_delta = t->ts_ms - prev_ts;
        buf_pos += agtick_encode_varint((uint64_t)ts_delta, buffer + buf_pos);
        prev_ts = t->ts_ms;

        /* Delta-encode price (signed) */
        int64_t price_delta = t->price_tick - prev_price;
        buf_pos += agtick_encode_svarint(price_delta, buffer + buf_pos);
        prev_price = t->price_tick;

        /* Encode quantity */
        buf_pos += agtick_encode_varint((uint64_t)t->qty, buffer + buf_pos);

        /* Pack side bit */
        if (t->side == SIDE_SELL) {
            side_buffer[i / 8] |= (1 << (i % 8));
        }
    }

    size_t tick_data_size = buf_pos;
    size_t side_data_size = (count + 7) / 8;

    /* Prepare header */
    agtick_header_t header;
    memset(&header, 0, sizeof(header));
    memcpy(header.magic, AGTICK_MAGIC, AGTICK_MAGIC_LEN);
    header.version = AGTICK_VERSION;

    /* Copy symbol (truncate if too long) */
    size_t sym_len = strlen(symbol);
    if (sym_len >= AGTICK_SYMBOL_LEN) {
        sym_len = AGTICK_SYMBOL_LEN - 1;
    }
    memcpy(header.symbol, symbol, sym_len);

    header.tick_size = tick_size;
    header.start_ts = count > 0 ? ticks[0].ts_ms : 0;
    header.end_ts = count > 0 ? ticks[count - 1].ts_ms : 0;
    header.tick_count = count;
    header.data_offset = AGTICK_HEADER_SIZE;

    /* Write header */
    if (fwrite(&header, sizeof(header), 1, fp) != 1) {
        result = AGTICK_ERR_IO;
        goto cleanup;
    }

    /* Write tick data */
    if (tick_data_size > 0) {
        if (fwrite(buffer, 1, tick_data_size, fp) != tick_data_size) {
            result = AGTICK_ERR_IO;
            goto cleanup;
        }
    }

    /* Write side bits */
    if (side_data_size > 0) {
        if (fwrite(side_buffer, 1, side_data_size, fp) != side_data_size) {
            result = AGTICK_ERR_IO;
            goto cleanup;
        }
    }

cleanup:
    if (fp) fclose(fp);
    free(buffer);
    free(side_buffer);
    return result;
}

/* ========== Reading Functions ========== */

int agtick_read(const char* path,
                tick_event_t** ticks_out,
                uint64_t* count_out,
                agtick_header_t* header_out)
{
    FILE* fp = NULL;
    uint8_t* buffer = NULL;
    tick_event_t* ticks = NULL;
    int result = AGTICK_OK;

    /* Validate parameters */
    if (!path || !ticks_out || !count_out) {
        return AGTICK_ERR_PARAM;
    }

    *ticks_out = NULL;
    *count_out = 0;

    /* Open file */
    fp = fopen(path, "rb");
    if (!fp) {
        return AGTICK_ERR_IO;
    }

    /* Read header */
    agtick_header_t header;
    if (fread(&header, sizeof(header), 1, fp) != 1) {
        result = AGTICK_ERR_IO;
        goto cleanup;
    }

    /* Validate magic */
    if (memcmp(header.magic, AGTICK_MAGIC, AGTICK_MAGIC_LEN) != 0) {
        result = AGTICK_ERR_MAGIC;
        goto cleanup;
    }

    /* Validate version */
    if (header.version != AGTICK_VERSION) {
        result = AGTICK_ERR_VERSION;
        goto cleanup;
    }

    if (header_out) {
        *header_out = header;
    }

    /* Handle empty file */
    if (header.tick_count == 0) {
        *ticks_out = NULL;
        *count_out = 0;
        goto cleanup;
    }

    /* Get file size and read remaining data */
    long current_pos = ftell(fp);
    fseek(fp, 0, SEEK_END);
    long file_size = ftell(fp);
    fseek(fp, current_pos, SEEK_SET);

    size_t data_size = (size_t)(file_size - current_pos);
    buffer = (uint8_t*)malloc(data_size);
    if (!buffer) {
        result = AGTICK_ERR_NOMEM;
        goto cleanup;
    }

    if (fread(buffer, 1, data_size, fp) != data_size) {
        result = AGTICK_ERR_IO;
        goto cleanup;
    }

    /* Allocate tick array */
    ticks = (tick_event_t*)malloc(header.tick_count * sizeof(tick_event_t));
    if (!ticks) {
        result = AGTICK_ERR_NOMEM;
        goto cleanup;
    }

    /* Calculate side data offset */
    size_t side_data_size = (header.tick_count + 7) / 8;
    size_t tick_data_size = data_size - side_data_size;
    const uint8_t* tick_data = buffer;
    const uint8_t* side_data = buffer + tick_data_size;

    /* Decode ticks */
    size_t pos = 0;
    int64_t prev_ts = 0;
    int64_t prev_price = 0;

    for (uint64_t i = 0; i < header.tick_count; i++) {
        tick_event_t* t = &ticks[i];
        int n;

        /* Decode timestamp delta */
        uint64_t ts_delta;
        n = agtick_decode_varint(tick_data + pos, tick_data_size - pos, &ts_delta);
        if (n < 0) {
            result = AGTICK_ERR_CORRUPT;
            goto cleanup;
        }
        pos += n;
        prev_ts += (int64_t)ts_delta;
        t->ts_ms = prev_ts;

        /* Decode price delta */
        int64_t price_delta;
        n = agtick_decode_svarint(tick_data + pos, tick_data_size - pos, &price_delta);
        if (n < 0) {
            result = AGTICK_ERR_CORRUPT;
            goto cleanup;
        }
        pos += n;
        prev_price += price_delta;
        t->price_tick = prev_price;

        /* Decode quantity */
        uint64_t qty;
        n = agtick_decode_varint(tick_data + pos, tick_data_size - pos, &qty);
        if (n < 0) {
            result = AGTICK_ERR_CORRUPT;
            goto cleanup;
        }
        pos += n;
        t->qty = (int64_t)qty;

        /* Decode side bit */
        uint8_t side_byte = side_data[i / 8];
        t->side = (side_byte & (1 << (i % 8))) ? SIDE_SELL : SIDE_BUY;
    }

    *ticks_out = ticks;
    *count_out = header.tick_count;
    ticks = NULL;  /* Transfer ownership */

cleanup:
    if (fp) fclose(fp);
    free(buffer);
    free(ticks);
    return result;
}

void agtick_free_ticks(tick_event_t* ticks)
{
    free(ticks);
}

/* ========== Memory Mapping Functions ========== */

#ifdef _WIN32

agtick_mmap_handle_t* agtick_mmap_open(const char* path)
{
    agtick_mmap_handle_t* handle = NULL;
    HANDLE file_handle = INVALID_HANDLE_VALUE;
    HANDLE map_handle = NULL;
    void* data = NULL;

    if (!path) return NULL;

    /* Open file */
    file_handle = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL,
                              OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (file_handle == INVALID_HANDLE_VALUE) {
        return NULL;
    }

    /* Get file size */
    LARGE_INTEGER file_size;
    if (!GetFileSizeEx(file_handle, &file_size)) {
        CloseHandle(file_handle);
        return NULL;
    }

    /* Create file mapping */
    map_handle = CreateFileMappingA(file_handle, NULL, PAGE_READONLY, 0, 0, NULL);
    if (!map_handle) {
        CloseHandle(file_handle);
        return NULL;
    }

    /* Map view */
    data = MapViewOfFile(map_handle, FILE_MAP_READ, 0, 0, 0);
    if (!data) {
        CloseHandle(map_handle);
        CloseHandle(file_handle);
        return NULL;
    }

    /* Validate header */
    if ((size_t)file_size.QuadPart < sizeof(agtick_header_t)) {
        UnmapViewOfFile(data);
        CloseHandle(map_handle);
        CloseHandle(file_handle);
        return NULL;
    }

    const agtick_header_t* hdr = (const agtick_header_t*)data;
    if (memcmp(hdr->magic, AGTICK_MAGIC, AGTICK_MAGIC_LEN) != 0 ||
        hdr->version != AGTICK_VERSION) {
        UnmapViewOfFile(data);
        CloseHandle(map_handle);
        CloseHandle(file_handle);
        return NULL;
    }

    /* Allocate handle */
    handle = (agtick_mmap_handle_t*)calloc(1, sizeof(agtick_mmap_handle_t));
    if (!handle) {
        UnmapViewOfFile(data);
        CloseHandle(map_handle);
        CloseHandle(file_handle);
        return NULL;
    }

    /* Initialize handle */
    handle->data = data;
    handle->size = (size_t)file_size.QuadPart;
    handle->header = *hdr;
    handle->file_handle = file_handle;
    handle->map_handle = map_handle;

    /* Calculate data pointers */
    size_t side_data_size = (hdr->tick_count + 7) / 8;
    size_t tick_data_size = handle->size - AGTICK_HEADER_SIZE - side_data_size;
    handle->tick_data = (const uint8_t*)data + AGTICK_HEADER_SIZE;
    handle->side_data = handle->tick_data + tick_data_size;
    handle->tick_data_len = tick_data_size;

    /* Initialize iterator */
    agtick_mmap_reset(handle);

    return handle;
}

void agtick_mmap_close(agtick_mmap_handle_t* handle)
{
    if (!handle) return;

    if (handle->data) {
        UnmapViewOfFile(handle->data);
    }
    if (handle->map_handle) {
        CloseHandle(handle->map_handle);
    }
    if (handle->file_handle != INVALID_HANDLE_VALUE) {
        CloseHandle(handle->file_handle);
    }
    free(handle);
}

#else /* POSIX */

agtick_mmap_handle_t* agtick_mmap_open(const char* path)
{
    agtick_mmap_handle_t* handle = NULL;
    int fd = -1;
    void* data = MAP_FAILED;

    if (!path) return NULL;

    /* Open file */
    fd = open(path, O_RDONLY);
    if (fd < 0) {
        return NULL;
    }

    /* Get file size */
    struct stat st;
    if (fstat(fd, &st) < 0) {
        close(fd);
        return NULL;
    }

    /* Map file */
    data = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    if (data == MAP_FAILED) {
        close(fd);
        return NULL;
    }

    /* Validate header */
    if ((size_t)st.st_size < sizeof(agtick_header_t)) {
        munmap(data, st.st_size);
        close(fd);
        return NULL;
    }

    const agtick_header_t* hdr = (const agtick_header_t*)data;
    if (memcmp(hdr->magic, AGTICK_MAGIC, AGTICK_MAGIC_LEN) != 0 ||
        hdr->version != AGTICK_VERSION) {
        munmap(data, st.st_size);
        close(fd);
        return NULL;
    }

    /* Allocate handle */
    handle = (agtick_mmap_handle_t*)calloc(1, sizeof(agtick_mmap_handle_t));
    if (!handle) {
        munmap(data, st.st_size);
        close(fd);
        return NULL;
    }

    /* Initialize handle */
    handle->data = data;
    handle->size = st.st_size;
    handle->header = *hdr;
    handle->fd = fd;

    /* Calculate data pointers */
    size_t side_data_size = (hdr->tick_count + 7) / 8;
    size_t tick_data_size = handle->size - AGTICK_HEADER_SIZE - side_data_size;
    handle->tick_data = (const uint8_t*)data + AGTICK_HEADER_SIZE;
    handle->side_data = handle->tick_data + tick_data_size;
    handle->tick_data_len = tick_data_size;

    /* Initialize iterator */
    agtick_mmap_reset(handle);

    return handle;
}

void agtick_mmap_close(agtick_mmap_handle_t* handle)
{
    if (!handle) return;

    if (handle->data && handle->data != MAP_FAILED) {
        munmap(handle->data, handle->size);
    }
    if (handle->fd >= 0) {
        close(handle->fd);
    }
    free(handle);
}

#endif /* _WIN32 / POSIX */

/* ========== Common Mmap Functions ========== */

const agtick_header_t* agtick_mmap_header(agtick_mmap_handle_t* handle)
{
    if (!handle) return NULL;
    return &handle->header;
}

void agtick_mmap_reset(agtick_mmap_handle_t* handle)
{
    if (!handle) return;

    handle->iter_pos = handle->tick_data;
    handle->iter_side_idx = 0;
    handle->prev_ts = 0;
    handle->prev_price = 0;
    handle->ticks_read = 0;
}

int agtick_mmap_next(agtick_mmap_handle_t* handle, tick_event_t* tick_out)
{
    if (!handle || !tick_out) {
        return AGTICK_ERR_PARAM;
    }

    /* Check if we've read all ticks */
    if (handle->ticks_read >= handle->header.tick_count) {
        return 0;  /* End of data */
    }

    /* Calculate remaining buffer */
    size_t remaining = handle->tick_data_len - (handle->iter_pos - handle->tick_data);
    int n;

    /* Decode timestamp delta */
    uint64_t ts_delta;
    n = agtick_decode_varint(handle->iter_pos, remaining, &ts_delta);
    if (n < 0) return AGTICK_ERR_CORRUPT;
    handle->iter_pos += n;
    remaining -= n;
    handle->prev_ts += (int64_t)ts_delta;
    tick_out->ts_ms = handle->prev_ts;

    /* Decode price delta */
    int64_t price_delta;
    n = agtick_decode_svarint(handle->iter_pos, remaining, &price_delta);
    if (n < 0) return AGTICK_ERR_CORRUPT;
    handle->iter_pos += n;
    remaining -= n;
    handle->prev_price += price_delta;
    tick_out->price_tick = handle->prev_price;

    /* Decode quantity */
    uint64_t qty;
    n = agtick_decode_varint(handle->iter_pos, remaining, &qty);
    if (n < 0) return AGTICK_ERR_CORRUPT;
    handle->iter_pos += n;
    tick_out->qty = (int64_t)qty;

    /* Decode side bit */
    size_t side_idx = handle->iter_side_idx++;
    uint8_t side_byte = handle->side_data[side_idx / 8];
    tick_out->side = (side_byte & (1 << (side_idx % 8))) ? SIDE_SELL : SIDE_BUY;

    handle->ticks_read++;
    return 1;  /* Success */
}

int64_t agtick_mmap_decode_all(agtick_mmap_handle_t* handle,
                               tick_event_t* ticks_out,
                               uint64_t max_count)
{
    if (!handle || !ticks_out) {
        return AGTICK_ERR_PARAM;
    }

    /* Reset to beginning */
    agtick_mmap_reset(handle);

    uint64_t count = handle->header.tick_count;
    if (count > max_count) {
        count = max_count;
    }

    /* Decode all ticks */
    for (uint64_t i = 0; i < count; i++) {
        int ret = agtick_mmap_next(handle, &ticks_out[i]);
        if (ret <= 0) {
            return ret < 0 ? ret : (int64_t)i;
        }
    }

    return (int64_t)count;
}
