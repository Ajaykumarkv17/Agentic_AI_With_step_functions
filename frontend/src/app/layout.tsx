import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'AI Travel Concierge',
  description: 'Personalized travel itineraries for Indian travelers, powered by AI agents',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header style={{
          borderBottom: '1px solid var(--color-border)',
          padding: 'var(--space-md) var(--space-lg)',
        }}>
          <nav style={{ maxWidth: 1100, margin: '0 auto', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <a href="/" style={{ fontFamily: 'var(--font-display)', fontSize: '1.4rem', fontWeight: 700, color: 'var(--color-text)', letterSpacing: '-0.01em' }}>
              <span style={{ color: 'var(--color-accent)' }}>Voyage</span>AI
            </a>
            <span style={{ fontSize: '0.75rem', color: 'var(--color-text-dim)', letterSpacing: '0.06em', textTransform: 'uppercase' as const }}>
              Intelligent Travel Planning
            </span>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
