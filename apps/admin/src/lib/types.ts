export interface RoleBrief {
  id: string;
  key: string;
  name: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string | null;
  is_active: boolean;
  is_superuser: boolean;
  created_at: string;
  last_login_at: string | null;
  roles: RoleBrief[];
  permissions: string[];
}

export interface Permission {
  id: string;
  key: string;
  description: string | null;
}

export interface Role {
  id: string;
  key: string;
  name: string;
  description: string | null;
  is_system: boolean;
  created_at: string;
  permissions: Permission[];
}

export function hasPermission(user: Pick<User, "permissions">, perm: string): boolean {
  return user.permissions.includes("*") || user.permissions.includes(perm);
}
