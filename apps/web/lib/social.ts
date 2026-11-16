/** Social links for the Settings About block and MoreDrawer (design.md 5.5, Appendix B Q28). */
export function socialLinks(): { key: 'linkedin' | 'x' | 'github'; href: string }[] {
  const links = [
    { key: 'linkedin' as const, href: process.env.NEXT_PUBLIC_LINKEDIN_URL ?? '' },
    { key: 'x' as const, href: process.env.NEXT_PUBLIC_X_URL ?? '' },
    { key: 'github' as const, href: process.env.NEXT_PUBLIC_GITHUB_URL ?? '' },
  ];
  // Never ship a dead link: hide any link whose variable is empty (design.md 5.5).
  return links.filter((l) => /^https?:\/\//.test(l.href));
}
