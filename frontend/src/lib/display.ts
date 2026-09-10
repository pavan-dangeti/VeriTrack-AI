/** Identity display: human name when present, email as the stable fallback. */
export function displayName(u: { full_name?: string | null; email: string }): string {
  const n = u.full_name?.trim();
  return n || u.email;
}
