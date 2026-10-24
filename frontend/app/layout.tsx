import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

export const metadata: Metadata = {
  title: "MolTel",
  description: "MolTel — evidence-backed pharmaceutical research intelligence",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={inter.variable}>
      <body className="min-h-screen bg-slate-50 font-sans">
        {/* Navigation */}
        <nav className="sticky top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur-sm">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <div className="flex h-14 items-center">
              <a
                href="/"
                className="flex items-center gap-2 text-sm font-semibold tracking-widest text-slate-900 hover:text-indigo-600 transition-colors"
              >
                <span className="inline-block h-2 w-2 rounded-full bg-indigo-600" />
                MOLTEL
              </a>
            </div>
          </div>
        </nav>

        {/* Page content */}
        <main>{children}</main>

        {/* Footer */}
        <footer className="mt-16 border-t border-slate-200 bg-white py-6">
          <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
            <p className="text-center text-xs text-slate-400">
              MolTel — evidence synthesis from public scientific APIs.
              Not for clinical use.
            </p>
          </div>
        </footer>
      </body>
    </html>
  );
}
