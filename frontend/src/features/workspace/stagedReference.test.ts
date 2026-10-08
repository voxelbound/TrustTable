import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  forgetStagedReference,
  readStagedReference,
  rememberStagedReference,
} from './stagedReference'

describe('stagedReference', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    forgetStagedReference()
  })

  it('remembers, reads and forgets the reference in tab-scoped storage only', () => {
    expect(readStagedReference()).toBeNull()

    rememberStagedReference('abc')

    expect(readStagedReference()).toBe('abc')
    expect(window.sessionStorage.length).toBe(1)
    expect(window.localStorage.length).toBe(0)

    forgetStagedReference()

    expect(readStagedReference()).toBeNull()
  })

  it('treats an empty stored value as no reference', () => {
    window.sessionStorage.setItem('trusttable.stagedUploadReference', '')

    expect(readStagedReference()).toBeNull()
  })

  it('degrades to no reference instead of throwing when storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied')
    })
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => {
      throw new Error('denied')
    })

    expect(() => rememberStagedReference('abc')).not.toThrow()
    expect(readStagedReference()).toBeNull()
    expect(() => forgetStagedReference()).not.toThrow()
  })
})
