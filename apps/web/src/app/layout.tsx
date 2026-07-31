export const metadata = {
  title: "IgorAgent Control Plane",
  description: "Policy controls for a bounded Telegram AI agent",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
