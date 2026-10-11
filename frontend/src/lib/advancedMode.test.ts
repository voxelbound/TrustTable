import { act, renderHook } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { setAdvancedMode, useAdvancedMode } from './advancedMode'

describe('advanced mode', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('UX-08b: is Normal by default', () => {
    window.localStorage.clear()
    setAdvancedMode(false)
    window.localStorage.clear()

    const { result } = renderHook(() => useAdvancedMode())

    expect(result.current[0]).toBe(false)
  })

  it('UX-08b: keeps the choice in this browser and reads it back', () => {
    const { result } = renderHook(() => useAdvancedMode())

    act(() => result.current[1](true))

    expect(result.current[0]).toBe(true)
    expect(window.localStorage.getItem('trusttable.advanced-mode')).toBe('true')
    const second = renderHook(() => useAdvancedMode())
    expect(second.result.current[0]).toBe(true)
  })

  it('UX-08b: follows a change made in another tab', () => {
    const { result } = renderHook(() => useAdvancedMode())
    expect(result.current[0]).toBe(false)

    act(() => {
      window.localStorage.setItem('trusttable.advanced-mode', 'true')
      window.dispatchEvent(new StorageEvent('storage'))
    })

    expect(result.current[0]).toBe(true)
  })

  it('UX-08b: ignores a stored value that is not exactly true or false', () => {
    window.localStorage.setItem('trusttable.advanced-mode', 'yes')
    const { result } = renderHook(() => useAdvancedMode())

    expect(result.current[0]).toBe(false)
  })

  it('UX-08b: holds the choice for this page when the browser refuses storage', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError')
    })
    const { result } = renderHook(() => useAdvancedMode())

    act(() => result.current[1](true))

    expect(result.current[0]).toBe(true)
  })
})
