interface CitationProps {
  source: string;
  identifier: string;
  url?: string;
  title?: string;
}

export default function Citation({
  source,
  identifier,
  url,
  title,
}: CitationProps) {
  const label = `[${source} — ${identifier}]`;

  if (url) {
    return (
      <a
        href={url}
        target="_blank"
        rel="noopener noreferrer"
        className="inline-flex items-center gap-1 text-xs text-indigo-600 hover:text-indigo-800 hover:underline"
        title={title}
      >
        {label}
      </a>
    );
  }

  return (
    <span className="text-xs text-slate-500" title={title}>
      {label}
    </span>
  );
}
