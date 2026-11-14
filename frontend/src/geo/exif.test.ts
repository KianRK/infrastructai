import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { expect, test } from 'vitest'
import { readGpsPosition } from './exif.ts'

type Dms = [number, number, number]

interface GpsFields {
  little?: boolean
  latRef?: string
  lat?: Dms
  lonRef?: string
  lon?: Dms
  /** IFD0 entries before the GPS pointer, to check that the pointer is found among others. */
  extraIfd0Entries?: number
}

/** A JPEG consisting of SOI, one APP1 Exif segment and EOI, built byte by byte. */
function jpegWithGps(fields: GpsFields): ArrayBuffer {
  const { little = false, latRef = 'N', lat, lonRef = 'E', lon, extraIfd0Entries = 0 } = fields
  const gpsEntries: [number, number, number, number[] | null][] = [] // tag, type, count, rationals
  gpsEntries.push([1, 2, 2, null])
  if (lat) gpsEntries.push([2, 5, 3, lat])
  gpsEntries.push([3, 2, 2, null])
  if (lon) gpsEntries.push([4, 5, 3, lon])

  const ifd0Count = extraIfd0Entries + 1
  const ifd0Offset = 8
  const gpsOffset = ifd0Offset + 2 + ifd0Count * 12 + 4
  const gpsSize = 2 + gpsEntries.length * 12 + 4
  const dataOffset = gpsOffset + gpsSize
  const rationalCount = gpsEntries.filter(([, , , r]) => r).length
  const tiff = new DataView(new ArrayBuffer(dataOffset + rationalCount * 24))

  tiff.setUint16(0, little ? 0x4949 : 0x4d4d)
  tiff.setUint16(2, 42, little)
  tiff.setUint32(4, ifd0Offset, little)
  tiff.setUint16(ifd0Offset, ifd0Count, little)
  for (let i = 0; i < extraIfd0Entries; i++) {
    const at = ifd0Offset + 2 + i * 12
    tiff.setUint16(at, 0x0112, little) // Orientation, SHORT
    tiff.setUint16(at + 2, 3, little)
    tiff.setUint32(at + 4, 1, little)
    tiff.setUint16(at + 8, 1, little)
  }
  const pointer = ifd0Offset + 2 + extraIfd0Entries * 12
  tiff.setUint16(pointer, 0x8825, little)
  tiff.setUint16(pointer + 2, 4, little) // LONG
  tiff.setUint32(pointer + 4, 1, little)
  tiff.setUint32(pointer + 8, gpsOffset, little)

  tiff.setUint16(gpsOffset, gpsEntries.length, little)
  let data = dataOffset
  for (const [i, [tag, type, count, rationals]] of gpsEntries.entries()) {
    const at = gpsOffset + 2 + i * 12
    tiff.setUint16(at, tag, little)
    tiff.setUint16(at + 2, type, little)
    tiff.setUint32(at + 4, count, little)
    if (rationals) {
      tiff.setUint32(at + 8, data, little)
      for (const value of rationals) {
        // Written as value * 100 / 100, like cameras store fractional seconds.
        tiff.setUint32(data, Math.round(value * 100), little)
        tiff.setUint32(data + 4, 100, little)
        data += 8
      }
    } else {
      const ref = tag === 1 ? latRef : lonRef
      tiff.setUint8(at + 8, ref.charCodeAt(0)) // ASCII "N\0" fits inline
    }
  }

  const exifHeader = [0x45, 0x78, 0x69, 0x66, 0, 0]
  const segmentLength = 2 + exifHeader.length + tiff.byteLength
  const bytes = new Uint8Array(4 + segmentLength + 2 + 2)
  bytes.set([0xff, 0xd8, 0xff, 0xe1, segmentLength >> 8, segmentLength & 0xff], 0)
  bytes.set(exifHeader, 6)
  bytes.set(new Uint8Array(tiff.buffer), 12)
  bytes.set([0xff, 0xd9], bytes.length - 2)
  return bytes.buffer
}

function fixture(name: string): ArrayBuffer {
  // Tests run from the frontend directory (import.meta.url is not a file URL under jsdom).
  const bytes = readFileSync(join(process.cwd(), 'src/test/data', name))
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)
}

test('reads the position from a photo written by another program (Pillow)', () => {
  const position = readGpsPosition(fixture('gps-pillow.jpg'))
  expect(position?.lat).toBeCloseTo(50.0865, 6)
  expect(position?.lon).toBeCloseTo(14.411167, 6)
})

test('a photo without GPS data has no position', () => {
  expect(readGpsPosition(fixture('no-gps-pillow.jpg'))).toBeNull()
})

test.each([
  { little: false, name: 'big endian' },
  { little: true, name: 'little endian' },
])('reads degrees, minutes and seconds ($name)', ({ little }) => {
  const position = readGpsPosition(
    jpegWithGps({ little, lat: [35, 41, 22.2], lon: [139, 41, 30.12], extraIfd0Entries: 3 }),
  )
  expect(position?.lat).toBeCloseTo(35 + 41 / 60 + 22.2 / 3600, 9)
  expect(position?.lon).toBeCloseTo(139 + 41 / 60 + 30.12 / 3600, 9)
})

test('south and west are negative', () => {
  const position = readGpsPosition(
    jpegWithGps({ latRef: 'S', lat: [12, 2, 0], lonRef: 'W', lon: [77, 1, 30] }),
  )
  expect(position?.lat).toBeCloseTo(-(12 + 2 / 60), 9)
  expect(position?.lon).toBeCloseTo(-(77 + 1 / 60 + 30 / 3600), 9)
})

test('incomplete or impossible positions are ignored', () => {
  expect(readGpsPosition(jpegWithGps({ lat: [35, 0, 0] }))).toBeNull() // no longitude
  expect(readGpsPosition(jpegWithGps({ lat: [0, 0, 0], lon: [0, 0, 0] }))).toBeNull()
  expect(readGpsPosition(jpegWithGps({ lat: [95, 0, 0], lon: [10, 0, 0] }))).toBeNull()
})

test('other files and damaged data give no position instead of an error', () => {
  const png = new Uint8Array([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]).buffer
  expect(readGpsPosition(png)).toBeNull()
  expect(readGpsPosition(new ArrayBuffer(0))).toBeNull()
  const whole = new Uint8Array(jpegWithGps({ lat: [35, 0, 0], lon: [139, 0, 0] }))
  for (const length of [3, 20, 40, 80, whole.length - 30]) {
    expect(readGpsPosition(whole.slice(0, length).buffer)).toBeNull()
  }
})
