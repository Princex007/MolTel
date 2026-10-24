import type { CompoundProfile } from "@/lib/api";

interface CompoundCardProps {
  compound: CompoundProfile;
}

interface PropertyRowProps {
  label: string;
  value: string | null | undefined;
  mono?: boolean;
  truncate?: boolean;
}

function PropertyRow({ label, value, mono, truncate }: PropertyRowProps) {
  if (!value) return null;
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
      <dt className="w-40 shrink-0 text-xs font-medium text-slate-500">{label}</dt>
      <dd
        className={`text-sm text-slate-900 ${mono ? "font-mono" : ""} ${
          truncate ? "truncate" : "break-all"
        }`}
      >
        {value}
      </dd>
    </div>
  );
}

export default function CompoundCard({ compound }: CompoundCardProps) {
  const displaySynonyms = compound.synonyms.slice(0, 5).join(", ");

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
      {/* Header */}
      <div className="mb-4 flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-semibold text-slate-900">
            {compound.name ?? "Unknown Compound"}
          </h3>
          {compound.cid && (
            <a
              href={`https://pubchem.ncbi.nlm.nih.gov/compound/${compound.cid}`}
              target="_blank"
              rel="noopener noreferrer"
              className="text-xs text-indigo-600 hover:underline"
            >
              PubChem CID: {compound.cid}
            </a>
          )}
        </div>
        {compound.molecular_formula && (
          <span className="shrink-0 rounded bg-slate-100 px-2 py-1 font-mono text-sm font-medium text-slate-700">
            {compound.molecular_formula}
          </span>
        )}
      </div>

      {/* Properties */}
      <dl className="flex flex-col gap-2.5">
        <PropertyRow label="Molecular Weight" value={compound.molecular_weight} />
        <PropertyRow label="IUPAC Name" value={compound.iupac_name} />
        <PropertyRow label="InChIKey" value={compound.inchi_key} mono />
        <PropertyRow
          label="Canonical SMILES"
          value={compound.canonical_smiles}
          mono
          truncate
        />
        {compound.isomeric_smiles &&
          compound.isomeric_smiles !== compound.canonical_smiles && (
            <PropertyRow
              label="Isomeric SMILES"
              value={compound.isomeric_smiles}
              mono
              truncate
            />
          )}
        {displaySynonyms && (
          <PropertyRow label="Synonyms" value={displaySynonyms} />
        )}
      </dl>
    </div>
  );
}
