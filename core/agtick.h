/**
 * ag-kernel Custom Binary Tick Format (.agtick)
 *
 * A compact, efficient binary format for storing tick data optimized for
 * backtesting workloads. Provides 5-10x compression over CSV and 10-50x
 * faster loading with optional zero-copy memory mapping.
 *
 * Format Specification (Version 1):
 * =================================
 *
 * File Header (64 bytes fixed):
 *   [0-3]   Magic bytes: "AGTK" (4 bytes)
 *   [4]     Version: 1 (1 byte)
 *   [5-7]   Flags (3 bytes, reserved)
 *   [8-23]  Symbol (16 bytes, null-padded)
 *   [24-31] Tick size as double (8 bytes)
 *   [32-39] Start timestamp ms (8 bytes)
 *   [40-47] End timestamp ms (8 bytes)
 *   [48-55] Tick count (8 bytes)
 *   [56-63] Data offset (8 bytes, offset to tick data)
 *
 * Tick Data (variable length):
 *   Each tick is encoded as:
 *   - ts_delta:    Varint (delta from previous timestamp in ms)
 *   - price_delta: Signed varint (delta from previous price in ticks)
 *   - qty:         Varint (quantity)
 *   - side:        Bit-packed (8 sides per byte, read separately)
 *
 *   Side bits are stored in a separate block after all tick fields,
 *   enabling better compression and cache behavior.
 *
 * Encoding Details:
 * - Varint: Standard unsigned LEB128 encoding
 * - Signed varint: ZigZag encoding then LEB128
 * - Side bits: Packed LSB-first, 8 per byte
 */

#ifndef AG_KERNEL_AGTICK_H
#define AG_KERNEL_AGTICK_H

#include <stdint.h>
#include <stddef.h>
#include "types.h"

#ifdef __cplusplus
extern "C" {
#endif

/* Magic bytes for file identification */
#define AGTICK_MAGIC "AGTK"
#define AGTICK_MAGIC_LEN 4

/* Current format version */
#define AGTICK_VERSION 1

/* Maximum symbol length (including null terminator) */
#define AGTICK_SYMBOL_LEN 16

/* Header size in bytes (fixed) */
#define AGTICK_HEADER_SIZE 64

/* Error codes */
#define AGTICK_OK             0
#define AGTICK_ERR_IO        -1
#define AGTICK_ERR_MAGIC     -2
#define AGTICK_ERR_VERSION   -3
#define AGTICK_ERR_CORRUPT   -4
#define AGTICK_ERR_NOMEM     -5
#define AGTICK_ERR_PARAM     -6
#define AGTICK_ERR_MMAP      -7

/**
 * File header structure (64 bytes, packed)
 */
#pragma pack(push, 1)
typedef struct {
    char     magic[AGTICK_MAGIC_LEN];  /* "AGTK" */
    uint8_t  version;                   /* Format version (1) */
    uint8_t  flags[3];                  /* Reserved flags */
    char     symbol[AGTICK_SYMBOL_LEN]; /* Symbol name, null-padded */
    double   tick_size;                 /* Tick size in currency units */
    int64_t  start_ts;                  /* First tick timestamp (ms) */
    int64_t  end_ts;                    /* Last tick timestamp (ms) */
    uint64_t tick_count;                /* Number of ticks */
    uint64_t data_offset;               /* Offset to tick data */
} agtick_header_t;
#pragma pack(pop)

/**
 * Handle for memory-mapped agtick file
 */
typedef struct agtick_mmap_handle_s agtick_mmap_handle_t;

/**
 * Write tick data to an agtick file.
 *
 * @param path      Output file path
 * @param ticks     Array of tick events to write
 * @param count     Number of ticks
 * @param symbol    Symbol name (max 15 chars)
 * @param tick_size Tick size in currency units
 * @return AGTICK_OK on success, negative error code on failure
 */
int agtick_write(const char* path,
                 const tick_event_t* ticks,
                 uint64_t count,
                 const char* symbol,
                 double tick_size);

/**
 * Read tick data from an agtick file.
 * Allocates memory for the tick array; caller must free with agtick_free_ticks().
 *
 * @param path       Input file path
 * @param ticks_out  Output pointer for tick array (allocated)
 * @param count_out  Output pointer for tick count
 * @param header_out Optional output for header info (can be NULL)
 * @return AGTICK_OK on success, negative error code on failure
 */
int agtick_read(const char* path,
                tick_event_t** ticks_out,
                uint64_t* count_out,
                agtick_header_t* header_out);

/**
 * Free tick array allocated by agtick_read().
 *
 * @param ticks Tick array to free
 */
void agtick_free_ticks(tick_event_t* ticks);

/**
 * Memory-map an agtick file for zero-copy reading.
 * The file remains mapped until agtick_mmap_close() is called.
 *
 * @param path Input file path
 * @return Handle on success, NULL on failure
 */
agtick_mmap_handle_t* agtick_mmap_open(const char* path);

/**
 * Get the header from a memory-mapped agtick file.
 *
 * @param handle Mmap handle
 * @return Pointer to header (valid until close), NULL on error
 */
const agtick_header_t* agtick_mmap_header(agtick_mmap_handle_t* handle);

/**
 * Decode a single tick from a memory-mapped file.
 * Uses internal iterator state; call agtick_mmap_reset() to restart.
 *
 * @param handle   Mmap handle
 * @param tick_out Output tick event
 * @return 1 if tick decoded, 0 if end of data, negative on error
 */
int agtick_mmap_next(agtick_mmap_handle_t* handle, tick_event_t* tick_out);

/**
 * Reset the iterator to the beginning of tick data.
 *
 * @param handle Mmap handle
 */
void agtick_mmap_reset(agtick_mmap_handle_t* handle);

/**
 * Decode all ticks from memory-mapped file into provided buffer.
 * More efficient than calling agtick_mmap_next() in a loop.
 *
 * @param handle    Mmap handle
 * @param ticks_out Pre-allocated buffer for ticks
 * @param max_count Maximum ticks to decode
 * @return Number of ticks decoded, negative on error
 */
int64_t agtick_mmap_decode_all(agtick_mmap_handle_t* handle,
                               tick_event_t* ticks_out,
                               uint64_t max_count);

/**
 * Close and unmap a memory-mapped agtick file.
 *
 * @param handle Mmap handle to close
 */
void agtick_mmap_close(agtick_mmap_handle_t* handle);

/**
 * Get error message for an error code.
 *
 * @param err Error code
 * @return Static error message string
 */
const char* agtick_strerror(int err);

/* ========== Varint Encoding Utilities ========== */

/**
 * Encode unsigned 64-bit integer as varint (LEB128).
 *
 * @param value  Value to encode
 * @param buf    Output buffer (must have at least 10 bytes)
 * @return Number of bytes written
 */
int agtick_encode_varint(uint64_t value, uint8_t* buf);

/**
 * Decode varint (LEB128) to unsigned 64-bit integer.
 *
 * @param buf       Input buffer
 * @param buf_len   Buffer length
 * @param value_out Output value
 * @return Number of bytes read, negative on error
 */
int agtick_decode_varint(const uint8_t* buf, size_t buf_len, uint64_t* value_out);

/**
 * Encode signed 64-bit integer using ZigZag encoding then varint.
 *
 * @param value  Value to encode
 * @param buf    Output buffer (must have at least 10 bytes)
 * @return Number of bytes written
 */
int agtick_encode_svarint(int64_t value, uint8_t* buf);

/**
 * Decode ZigZag-encoded varint to signed 64-bit integer.
 *
 * @param buf       Input buffer
 * @param buf_len   Buffer length
 * @param value_out Output value
 * @return Number of bytes read, negative on error
 */
int agtick_decode_svarint(const uint8_t* buf, size_t buf_len, int64_t* value_out);

#ifdef __cplusplus
}
#endif

#endif /* AG_KERNEL_AGTICK_H */
