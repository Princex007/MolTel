/**
 * Word export via the `docx` package — a genuine OOXML .docx container, not an
 * HTML file renamed to look like one. Headings, tables, hyperlinks and embedded
 * PNG figures are native document content, so the file opens and stays editable
 * in Word with no browser and no network.
 */

import {
  AlignmentType,
  Document,
  ExternalHyperlink,
  Footer,
  HeadingLevel,
  ImageRun,
  PageNumber,
  Packer,
  Paragraph,
  ShadingType,
  Table,
  TableCell,
  TableRow,
  TextRun,
  WidthType,
} from "docx";
import type { ChartSpec } from "../trialCharts";
import type { RasterImage } from "../rasterize";
import { PRODUCT_NAME, type ReportModel, type ReportSection, type ReportTable } from "../report";

const DOCX_MIME =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document";

// A4 with 1in margins: 9029 twips of usable width.
const CONTENT_TWIPS = 9029;
// docx sizes images in CSS pixels at 96 dpi.
const CONTENT_PX = Math.round(CONTENT_TWIPS / 1440) * 96;

type Block = Paragraph | Table;

function isUrl(text: string): boolean {
  return /^https?:\/\/\S+$/.test(text.trim());
}

const COLUMN_HINTS: Record<string, number> = {
  title: 3.2,
  statement: 3,
  function: 2.6,
  name: 1.5,
  explanation: 2.2,
  detail: 1.8,
  link: 1.4,
  url: 1.4,
  year: 0.6,
  records: 0.8,
  status: 1,
  phase: 1.3,
  source: 1.2,
  published: 0.9,
  indexed: 1,
  "records merged": 1.1,
};

function cellParagraph(text: string, opts: { bold?: boolean; size?: number } = {}): Paragraph {
  const size = opts.size ?? 14; // half-points, so 14 = 7pt inside tables
  if (isUrl(text) && !opts.bold) {
    return new Paragraph({
      children: [
        new ExternalHyperlink({
          link: text.trim(),
          children: [
            new TextRun({
              text: text.trim().replace(/^https?:\/\//, "").slice(0, 60),
              style: "Hyperlink",
              size,
            }),
          ],
        }),
      ],
    });
  }
  // A literal newline is not a break in Word; each line needs its own run.
  const lines = text.split("\n");
  return new Paragraph({
    children: lines.map(
      (line, i) =>
        new TextRun({ text: line, bold: opts.bold, size, ...(i ? { break: 1 } : {}) })
    ),
  });
}

function buildTable(table: ReportTable): Block[] {
  const weights = table.columns.map((c) => COLUMN_HINTS[c.toLowerCase()] ?? 1.2);
  const total = weights.reduce((s, x) => s + x, 0);
  const columnWidths = weights.map((x) => Math.round((CONTENT_TWIPS * x) / total));

  const header = new TableRow({
    tableHeader: true,
    children: table.columns.map(
      (col, i) =>
        new TableCell({
          width: { size: columnWidths[i], type: WidthType.DXA },
          shading: { type: ShadingType.CLEAR, fill: "EEF2FF", color: "auto" },
          margins: { top: 40, bottom: 40, left: 60, right: 60 },
          children: [cellParagraph(col, { bold: true })],
        })
    ),
  });

  const body = table.rows.map(
    (row) =>
      new TableRow({
        children: table.columns.map(
          (_, i) =>
            new TableCell({
              width: { size: columnWidths[i] ?? 1000, type: WidthType.DXA },
              margins: { top: 30, bottom: 30, left: 60, right: 60 },
              children: [cellParagraph(String(row[i] ?? ""))],
            })
        ),
      })
  );

  const blocks: Block[] = [
    new Table({
      width: { size: 100, type: WidthType.PERCENTAGE },
      columnWidths,
      rows: table.rows.length ? [header, ...body] : [header],
    }),
  ];
  const notes = [table.note, table.omittedRows ? `${table.omittedRows} further row(s) are not printed here; the complete set is in the CSV export.` : ""]
    .filter(Boolean)
    .join(" ");
  if (notes) {
    blocks.push(
      new Paragraph({
        spacing: { before: 40, after: 160 },
        children: [new TextRun({ text: notes, italics: true, size: 16, color: "64748B" })],
      })
    );
  }
  return blocks;
}

function callout(title: string, text: string): Block[] {
  return [
    new Paragraph({
      spacing: { before: 120, after: 40 },
      shading: { type: ShadingType.CLEAR, fill: "FEF9E7", color: "auto" },
      children: [new TextRun({ text: title, bold: true, size: 20, color: "92400E" })],
    }),
    new Paragraph({
      spacing: { after: 160 },
      shading: { type: ShadingType.CLEAR, fill: "FEF9E7", color: "auto" },
      children: [new TextRun({ text, size: 19, color: "7C5A19" })],
    }),
  ];
}

function figure(chart: ChartSpec, image: RasterImage | undefined): Block[] {
  if (!image) {
    return [
      new Paragraph({
        spacing: { before: 120, after: 120 },
        children: [
          new TextRun({
            text: `Figure "${chart.title}" could not be rendered in this browser and is omitted. The underlying records remain in the table below and in the CSV export.`,
            italics: true,
            color: "B91C1C",
            size: 18,
          }),
        ],
      }),
    ];
  }
  const width = CONTENT_PX;
  const height = Math.max(1, Math.round((image.height / image.width) * CONTENT_PX));
  return [
    new Paragraph({
      spacing: { before: 160, after: 40 },
      alignment: AlignmentType.CENTER,
      children: [
        new ImageRun({
          type: "png",
          data: new Uint8Array(image.bytes),
          transformation: { width, height },
        }),
      ],
    }),
    new Paragraph({
      spacing: { after: 160 },
      children: [
        new TextRun({
          text: `Figure: ${chart.title}. ${chart.subtitle} Counts ${chart.unit}.`,
          italics: true,
          size: 16,
          color: "64748B",
        }),
      ],
    }),
  ];
}

function renderSection(section: ReportSection, images: Map<string, RasterImage>): Block[] {
  const out: Block[] = [
    new Paragraph({
      heading: HeadingLevel.HEADING_2,
      spacing: { before: 260, after: 80 },
      children: [new TextRun({ text: `${section.number}. ${section.title}`, bold: true })],
    }),
  ];
  if (section.description) {
    out.push(
      new Paragraph({
        spacing: { after: 80 },
        children: [
          new TextRun({ text: section.description, italics: true, size: 18, color: "64748B" }),
        ],
      })
    );
  }
  for (const node of section.nodes) {
    switch (node.kind) {
      case "prose":
        out.push(
          new Paragraph({
            spacing: { after: 120 },
            children: [new TextRun({ text: node.text, size: 21 })],
          })
        );
        break;
      case "bullets":
        node.items.forEach((item) =>
          out.push(
            new Paragraph({
              bullet: { level: 0 },
              spacing: { after: 40 },
              children: [new TextRun({ text: item, size: 21 })],
            })
          )
        );
        break;
      case "callout":
        out.push(...callout(node.title, node.text));
        break;
      case "kv":
        node.entries.forEach(([label, value]) =>
          out.push(
            new Paragraph({
              spacing: { after: 30 },
              children: [
                new TextRun({ text: `${label}: `, bold: true, size: 20 }),
                new TextRun({ text: String(value), size: 20 }),
              ],
            })
          )
        );
        break;
      case "table":
        out.push(...buildTable(node.table));
        break;
      case "charts":
        node.charts.forEach((chart) => out.push(...figure(chart, images.get(chart.id))));
        break;
      case "references":
        out.push(
          new Paragraph({
            spacing: { before: 120, after: 60 },
            children: [new TextRun({ text: "References", bold: true, size: 20 })],
          })
        );
        node.items.forEach((ref, i) =>
          out.push(
            new Paragraph({
              spacing: { after: 30 },
              children: [
                new TextRun({ text: `[${i + 1}] `, size: 18, color: "64748B" }),
                new TextRun({ text: ref, size: 18 }),
              ],
            })
          )
        );
        break;
    }
  }
  return out;
}

export async function buildDocx(
  model: ReportModel,
  images: Map<string, RasterImage>
): Promise<Blob> {
  const children: Block[] = [
    new Paragraph({
      heading: HeadingLevel.HEADING_1,
      spacing: { after: 40 },
      children: [new TextRun({ text: PRODUCT_NAME.toUpperCase(), bold: true })],
    }),
    new Paragraph({
      spacing: { after: 40 },
      children: [new TextRun({ text: model.title, size: 26, bold: true, color: "1E293B" })],
    }),
    new Paragraph({
      spacing: { after: 120 },
      children: [
        new TextRun({
          text: `Query "${model.query}"  |  ${model.statusLabel} retrieval  |  generated ${new Date().toLocaleString()}`,
          size: 18,
          color: "64748B",
        }),
      ],
    }),
    new Paragraph({
      spacing: { after: 200 },
      children: [
        new TextRun({
          text: "Every figure is computed from records retrieved from public scientific databases. AI-written interpretation, where present, is labelled. Not for clinical use.",
          italics: true,
          size: 18,
          color: "64748B",
        }),
      ],
    }),
  ];

  for (const section of model.sections) children.push(...renderSection(section, images));

  const doc = new Document({
    creator: PRODUCT_NAME,
    title: `${PRODUCT_NAME} — ${model.query}`,
    description: "Research dossier generated from public scientific databases",
    styles: { default: { document: { run: { font: "Calibri", size: 21 } } } },
    sections: [
      {
        properties: { page: { margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 } } },
        footers: {
          default: new Footer({
            children: [
              new Paragraph({
                children: [
                  new TextRun({
                    text: `${PRODUCT_NAME} — ${model.query}   |   Page `,
                    size: 16,
                    color: "94A3B8",
                  }),
                  new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "94A3B8" }),
                  new TextRun({ text: " of ", size: 16, color: "94A3B8" }),
                  new TextRun({ children: [PageNumber.TOTAL_PAGES], size: 16, color: "94A3B8" }),
                ],
              }),
            ],
          }),
        },
        children,
      },
    ],
  });

  const raw = await Packer.toBlob(doc);
  return new Blob([raw], { type: DOCX_MIME });
}
