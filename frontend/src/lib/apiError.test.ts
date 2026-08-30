import { describe, expect, it } from 'vitest'
import {
  FALLBACK_ERROR_MESSAGE,
  getApiErrorCode,
  getApiErrorMessage,
  isApiErrorEnvelope,
} from './apiError'

const CONFORMING_ENVELOPE = {
  error: {
    code: 'ANALYSIS_NOT_FOUND',
    message: 'The requested analysis was not found.',
    details: { analysis_id: 'abc-123' },
    request_id: 'req-1',
  },
}

describe('isApiErrorEnvelope', () => {
  it('recognizes a conforming envelope', () => {
    expect(isApiErrorEnvelope(CONFORMING_ENVELOPE)).toBe(true)
  })

  it('rejects null and non-object values', () => {
    expect(isApiErrorEnvelope(null)).toBe(false)
    expect(isApiErrorEnvelope(undefined)).toBe(false)
    expect(isApiErrorEnvelope('error')).toBe(false)
    expect(isApiErrorEnvelope(42)).toBe(false)
  })

  it('rejects an object with no error field', () => {
    expect(isApiErrorEnvelope({})).toBe(false)
  })

  it('rejects an error field missing a required string', () => {
    expect(
      isApiErrorEnvelope({
        error: { code: 'X', message: 'Y', details: {} },
      }),
    ).toBe(false)
  })

  it('rejects a non-conforming shape such as an HTML error page string', () => {
    expect(
      isApiErrorEnvelope('<html><body>502 Bad Gateway</body></html>'),
    ).toBe(false)
  })
})

describe('getApiErrorMessage', () => {
  it('extracts the message from a conforming envelope', () => {
    expect(getApiErrorMessage(CONFORMING_ENVELOPE)).toBe(
      'The requested analysis was not found.',
    )
  })

  it('falls back to a safe message for a non-conforming body without throwing', () => {
    expect(() => getApiErrorMessage(undefined)).not.toThrow()
    expect(getApiErrorMessage(undefined)).toBe(FALLBACK_ERROR_MESSAGE)
    expect(getApiErrorMessage({ detail: 'not our shape' })).toBe(
      FALLBACK_ERROR_MESSAGE,
    )
  })
})

describe('getApiErrorCode', () => {
  it('extracts the code from a conforming envelope', () => {
    expect(getApiErrorCode(CONFORMING_ENVELOPE)).toBe('ANALYSIS_NOT_FOUND')
  })

  it('returns null for a non-conforming body', () => {
    expect(getApiErrorCode(undefined)).toBeNull()
    expect(getApiErrorCode({})).toBeNull()
  })
})
