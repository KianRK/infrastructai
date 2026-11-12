import { expect, test } from 'vitest'
import { imageFile } from './test/fixtures.ts'
import { MAX_FILE_BYTES, validateImageFile } from './validation.ts'

test.each(['image/jpeg', 'image/png', 'image/webp'])('accepts %s', (type) => {
  expect(validateImageFile(imageFile('road', type))).toBeNull()
})

test.each([
  ['application/pdf', 'report.pdf'],
  ['image/svg+xml', 'drawing.svg'], // can carry scripts; the detector cannot read it anyway
  ['image/gif', 'anim.gif'],
  ['', 'unknown'],
])('rejects type "%s"', (type, name) => {
  expect(validateImageFile(imageFile(name, type))).toMatch(/JPEG, PNG or WebP/)
})

test('accepts a file exactly at the size limit and rejects one byte more', () => {
  expect(validateImageFile(imageFile('a.jpg', 'image/jpeg', MAX_FILE_BYTES))).toBeNull()
  expect(validateImageFile(imageFile('a.jpg', 'image/jpeg', MAX_FILE_BYTES + 1))).toMatch(
    /10\.0 MB; the limit is 10 MB/,
  )
})

test('rejects an empty file', () => {
  expect(validateImageFile(imageFile('a.jpg', 'image/jpeg', 0))).toBe('The file is empty.')
})
