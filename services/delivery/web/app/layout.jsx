import "./globals.css";

export const metadata = {
  title: "LOOM",
  description: "Live, Object-grounded, Orchestrated Media - personalization inside the frame",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link
          href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Inter:wght@400;500;600&family=JetBrains+Mono:wght@400;500&display=swap"
          rel="stylesheet"
        />
      </head>
      <body>
        <header className="topbar">
          <a href="/" className="brand">LOOM</a>
          <span className="tagline">Live · Object-grounded · Orchestrated Media</span>
          <nav>
            <a href="/">Library</a>
            <a href="/agents">Agents</a>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
