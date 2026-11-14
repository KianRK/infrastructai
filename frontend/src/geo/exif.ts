// Reads the GPS position from a JPEG's EXIF data, in the browser. Only what the map needs:
// latitude and longitude from the GPS IFD. The position never leaves the browser; the
// upload to the server is the unchanged file, and the server keeps nothing.
//
// Layout (EXIF 2.3 / TIFF 6.0): JPEG segment APP1 "Exif\0\0" -> TIFF header (byte order,
// offset of IFD0) -> IFD0 entry 0x8825 = offset of the GPS IFD -> GPS entries
// 1 LatitudeRef ("N"/"S"), 2 Latitude (3 rationals: degrees, minutes, seconds),
// 3 LongitudeRef ("E"/"W"), 4 Longitude.

export interface Position {
  lat: number
  lon: number
}

const GPS_IFD_POINTER = 0x8825
const ASCII = 2
const LONG = 4
const RATIONAL = 5

class Truncated extends Error {}

/** The position stored in the photo, or null (no EXIF, no GPS, not a JPEG, damaged data). */
export function readGpsPosition(buffer: ArrayBuffer): Position | null {
  try {
    const tiff = findExif(new DataView(buffer))
    return tiff ? readGps(tiff) : null
  } catch (error) {
    if (error instanceof Truncated || error instanceof RangeError) return null
    throw error
  }
}

/** The TIFF block inside the APP1 Exif segment, or null. */
function findExif(view: DataView): DataView | null {
  if (view.byteLength < 4 || view.getUint16(0) !== 0xffd8) return null // not a JPEG
  let offset = 2
  while (offset + 4 <= view.byteLength) {
    const marker = view.getUint16(offset)
    if ((marker & 0xff00) !== 0xff00) return null
    // Start of scan: image data follows, no more metadata segments.
    if (marker === 0xffda) return null
    const length = view.getUint16(offset + 2) // includes the two length bytes
    if (length < 2) return null
    if (marker === 0xffe1 && isExifHeader(view, offset + 4)) {
      const start = offset + 10
      const end = Math.min(offset + 2 + length, view.byteLength)
      return new DataView(view.buffer, view.byteOffset + start, Math.max(end - start, 0))
    }
    offset += 2 + length
  }
  return null
}

function isExifHeader(view: DataView, offset: number): boolean {
  if (offset + 6 > view.byteLength) return false
  // "Exif" followed by two zero bytes
  return view.getUint32(offset) === 0x45786966 && view.getUint16(offset + 4) === 0
}

function readGps(tiff: DataView): Position | null {
  const order = tiff.getUint16(0)
  if (order !== 0x4949 && order !== 0x4d4d) return null // "II" little, "MM" big endian
  const little = order === 0x4949
  if (tiff.getUint16(2, little) !== 42) return null

  const ifd0 = entries(tiff, tiff.getUint32(4, little), little)
  const pointer = ifd0.get(GPS_IFD_POINTER)
  if (pointer?.type !== LONG) return null
  const gps = entries(tiff, tiff.getUint32(pointer.field, little), little)

  const latRef = ascii(tiff, gps.get(1), little)
  const lat = degrees(tiff, gps.get(2), little)
  const lonRef = ascii(tiff, gps.get(3), little)
  const lon = degrees(tiff, gps.get(4), little)
  if (lat === null || lon === null || !latRef || !lonRef) return null

  const position = {
    lat: latRef.startsWith('S') ? -lat : lat,
    lon: lonRef.startsWith('W') ? -lon : lon,
  }
  // Cameras without a fix sometimes write zeros; (0, 0) is in the Gulf of Guinea.
  if (position.lat === 0 && position.lon === 0) return null
  if (Math.abs(position.lat) > 90 || Math.abs(position.lon) > 180) return null
  return position
}

interface Entry {
  type: number
  count: number
  /** Position of the entry's four-byte value field. */
  field: number
}

function entries(tiff: DataView, offset: number, little: boolean): Map<number, Entry> {
  if (offset + 2 > tiff.byteLength) throw new Truncated()
  const count = tiff.getUint16(offset, little)
  const found = new Map<number, Entry>()
  for (let i = 0; i < count; i++) {
    const at = offset + 2 + i * 12
    if (at + 12 > tiff.byteLength) throw new Truncated()
    found.set(tiff.getUint16(at, little), {
      type: tiff.getUint16(at + 2, little),
      count: tiff.getUint32(at + 4, little),
      field: at + 8,
    })
  }
  return found
}

/** Where the value starts: in the field itself if it fits in four bytes, else at the
 * offset the field holds. */
function valueStart(tiff: DataView, entry: Entry, size: number, little: boolean): number {
  return size <= 4 ? entry.field : tiff.getUint32(entry.field, little)
}

function ascii(tiff: DataView, entry: Entry | undefined, little: boolean): string | null {
  if (entry?.type !== ASCII || entry.count < 1) return null
  return String.fromCharCode(tiff.getUint8(valueStart(tiff, entry, entry.count, little)))
}

function degrees(tiff: DataView, entry: Entry | undefined, little: boolean): number | null {
  if (entry?.type !== RATIONAL || entry.count !== 3) return null
  const start = valueStart(tiff, entry, 24, little)
  let value = 0
  for (const [i, scale] of [1, 60, 3600].entries()) {
    const at = start + i * 8
    const numerator = tiff.getUint32(at, little)
    const denominator = tiff.getUint32(at + 4, little)
    if (denominator === 0) {
      if (numerator === 0) continue // "unknown" seconds, for example
      return null
    }
    value += numerator / denominator / scale
  }
  return value
}
