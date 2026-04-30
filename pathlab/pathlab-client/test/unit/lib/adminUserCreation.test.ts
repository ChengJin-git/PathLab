import { describe, expect, it } from 'vitest'

import { buildAdminCreateUserPlan } from '@renderer/lib/adminUserCreation'

describe('buildAdminCreateUserPlan', () => {
  it('always uses guest role for register payload and keeps target admin role', () => {
    const plan = buildAdminCreateUserPlan({
      username: 'new-admin',
      password: 'pass1234',
      nickname: 'Admin User',
      role: 'admin',
      registration_email: 'admin@example.com',
    })

    expect(plan.registerData).toMatchObject({
      username: 'new-admin',
      password: 'pass1234',
      nickname: 'Admin User',
      role: 'guest',
      registration_email: 'admin@example.com',
    })
    expect(plan.targetRole).toBe('admin')
  })

  it('normalizes unknown role to guest', () => {
    const plan = buildAdminCreateUserPlan({
      username: 'new-user',
      password: 'pass1234',
      nickname: '',
      role: 'unknown',
      registration_email: '',
    })

    expect(plan.registerData.role).toBe('guest')
    expect(plan.targetRole).toBe('guest')
    expect(plan.registerData.nickname).toBeUndefined()
    expect(plan.registerData.registration_email).toBeUndefined()
  })

  it('keeps pathologist as target role while register payload remains guest', () => {
    const plan = buildAdminCreateUserPlan({
      username: 'new-pathologist',
      password: 'pass1234',
      nickname: 'Pathologist',
      role: 'pathologist',
      registration_email: 'pathologist@example.com',
    })

    expect(plan.registerData.role).toBe('guest')
    expect(plan.targetRole).toBe('pathologist')
  })
})
