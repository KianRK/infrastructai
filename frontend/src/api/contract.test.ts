// @vitest-environment node
import { readFileSync } from 'node:fs'
import { expect, test } from 'vitest'
import { analysisWithDamage } from '../test/fixtures.ts'

/**
 * The backend commits its response schema; this test fails when a field is added,
 * removed or renamed there without updating types.ts and the fixture.
 */
interface ObjectSchema {
  properties: Record<string, unknown>
  required: string[]
}
interface Contract extends ObjectSchema {
  $defs: Record<string, ObjectSchema & { enum?: string[] }>
}

const contract = JSON.parse(
  readFileSync(
    new URL('../../../serving/contract/analysis_response.schema.json', import.meta.url),
    'utf8',
  ),
) as Contract

function keys(value: object): string[] {
  return Object.keys(value).sort()
}

test('response fields match the backend contract', () => {
  expect(keys(analysisWithDamage)).toEqual(keys(contract.properties))
  expect(keys(analysisWithDamage)).toEqual([...contract.required].sort())
})

test('detection and box fields match the backend contract', () => {
  const detection = analysisWithDamage.detections[0]
  expect(keys(detection)).toEqual(keys(contract.$defs.Detection.properties))
  expect(keys(detection.box)).toEqual(keys(contract.$defs.BoundingBox.properties))
})

test('damage classes match the backend contract', () => {
  const classes: Record<string, true> = { D00: true, D10: true, D20: true, D40: true }
  expect(keys(classes)).toEqual([...(contract.$defs.DamageClass.enum ?? [])].sort())
})
