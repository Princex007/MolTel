"use client";

import Citation from "./Citation";

interface Matcher {
  source: string;
  re: RegExp;
  label: (m: RegExpMatchArray) => string;
  url: (m: RegExpMatchArray) => string;
}

// Recognises the source identifiers the dossier emits so each reference turns
// into a working link back to the record it came from.
const MATCHERS: Matcher[] = [
  {
    source: "PubMed",
    re: /PMID[:\s]+(\d{6,9})/i,
    label: (m) => `PMID: ${m[1]}`,
    url: (m) => `https://pubmed.ncbi.nlm.nih.gov/${m[1]}/`,
  },
  {
    source: "DOI",
    re: /DOI[:\s]+(10\.\S+)/i,
    label: (m) => m[1],
    url: (m) => `https://doi.org/${m[1]}`,
  },
  {
    source: "ClinicalTrials.gov",
    re: /\b(NCT\d{8})\b/i,
    label: (m) => m[1],
    url: (m) => `https://clinicaltrials.gov/study/${m[1]}`,
  },
  {
    source: "PubChem",
    re: /CID[:\s]+(\d+)/i,
    label: (m) => `CID: ${m[1]}`,
    url: (m) => `https://pubchem.ncbi.nlm.nih.gov/compound/${m[1]}`,
  },
  {
    source: "UniProt",
    re: /UniProt[.\s]+([A-Z0-9]{5,10})$/i,
    label: (m) => m[1],
    url: (m) => `https://www.uniprot.org/uniprotkb/${m[1]}`,
  },
  {
    source: "openFDA",
    re: /\b((?:ANDA|NDA|BLA)\d{5,7})\b/i,
    label: (m) => m[1].toUpperCase(),
    url: (m) =>
      `https://api.fda.gov/drug/label.json?limit=1&search=application_number:%22${m[1].toUpperCase()}%22`,
  },
];

export function ReferenceCitation({
  reference,
  index = 0,
}: {
  reference: string;
  index?: number;
}) {
  for (const matcher of MATCHERS) {
    const m = reference.match(matcher.re);
    if (m) {
      return (
        <Citation
          key={index}
          source={matcher.source}
          identifier={matcher.label(m)}
          url={matcher.url(m)}
          title={reference}
        />
      );
    }
  }

  const urlMatch = reference.match(/https?:\/\/\S+/);
  if (urlMatch) {
    return (
      <Citation
        key={index}
        source="Link"
        identifier={urlMatch[0]}
        url={urlMatch[0]}
        title={reference}
      />
    );
  }

  return (
    <Citation key={index} source="Ref" identifier={`${index + 1}`} title={reference} />
  );
}

export default function ReferenceList({
  references,
  label = "Supporting records",
}: {
  references: string[];
  label?: string;
}) {
  if (references.length === 0) return null;
  return (
    <div className="mt-2">
      <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-400">
        {label}
      </p>
      <div className="mt-1 flex flex-wrap gap-1.5">
        {references.map((ref, i) => (
          <ReferenceCitation key={i} reference={ref} index={i} />
        ))}
      </div>
    </div>
  );
}
