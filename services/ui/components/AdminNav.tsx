import Link from "next/link";

const LINKS = [
  ["/admin", "Pipeline health"],
  ["/admin/demo", "Demo panel"],
  ["/admin/dead-letters", "Dead letters"],
] as const;

export function AdminNav({ current }: { current: string }) {
  return (
    <nav aria-label="Operator" className="flex gap-1 border-b border-line">
      {LINKS.map(([href, label]) => (
        <Link key={href} href={href} aria-current={current === href ? "page" : undefined} className={`px-3 py-1.5 text-sm ${current === href ? "border-b-2 border-accent" : "text-muted hover:text-fg"}`}>
          {label}
        </Link>
      ))}
    </nav>
  );
}
