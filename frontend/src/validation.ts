export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp'] as const
export const MAX_FILE_BYTES = 10 * 1024 * 1024

/**
 * Client-side check for fast feedback. The server validates again and is the
 * authority; this only saves the user a pointless upload.
 */
export function validateImageFile(file: File): string | null {
  if (!(ACCEPTED_TYPES as readonly string[]).includes(file.type)) {
    return 'Please choose a JPEG, PNG or WebP image.'
  }
  if (file.size === 0) {
    return 'The file is empty.'
  }
  if (file.size > MAX_FILE_BYTES) {
    const megabytes = (file.size / 1024 / 1024).toFixed(1)
    return `The image is ${megabytes} MB; the limit is 10 MB.`
  }
  return null
}
