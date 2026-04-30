import type { RegisterRequest } from '../api/auth'

export interface AdminCreateUserForm {
  username: string
  password: string
  nickname: string
  role: string
  registration_email: string
}

export type RequestedUserRole = 'admin' | 'pathologist' | 'guest'

export interface AdminCreateUserPlan {
  registerData: RegisterRequest
  targetRole: RequestedUserRole
}

function normalizeRequestedRole(role: string): RequestedUserRole {
  if (role === 'admin' || role === 'pathologist' || role === 'guest') {
    return role
  }
  return 'guest'
}

export function buildAdminCreateUserPlan(form: AdminCreateUserForm): AdminCreateUserPlan {
  const targetRole = normalizeRequestedRole(form.role)
  return {
    registerData: {
      username: form.username,
      password: form.password,
      nickname: form.nickname || undefined,
      role: 'guest',
      registration_email: form.registration_email || undefined,
    },
    targetRole,
  }
}
