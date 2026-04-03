"use client";

export default function PrivacyPage() {
  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-3xl mx-auto space-y-6">
        <h1 className="text-2xl font-bold text-white">Privacy Policy</h1>
        <p className="text-sm text-gray-400">Last updated: April 2026</p>

        <section className="space-y-3 text-gray-300 text-sm leading-relaxed">
          <h2 className="text-lg font-semibold text-white mt-6">What We Collect</h2>
          <p>When you create an account, we collect your email address and authentication credentials (managed by Firebase Authentication). We store the trade data, portfolio information, and theme assignments you enter into the application.</p>

          <h2 className="text-lg font-semibold text-white mt-6">How We Use Your Data</h2>
          <p>Your data is used solely to provide the portfolio tracking service. We do not sell, share, or distribute your personal or financial data to third parties. Your trade data is isolated to your account and not visible to other users.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Data Storage</h2>
          <p>Data is stored in Google Cloud Firestore (US region). Authentication is handled by Firebase Authentication. All data is transmitted over HTTPS. Each user's data is isolated using Firebase user IDs.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Third-Party Services</h2>
          <ul className="list-disc list-inside space-y-1">
            <li>Firebase Authentication (Google) — account management</li>
            <li>Google Cloud Firestore — data storage</li>
            <li>Yahoo Finance (via yfinance) — stock price data</li>
            <li>Vercel — application hosting</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">Data Export & Deletion</h2>
          <p>You can export all your data at any time via Settings &gt; Backup Export. To delete your account and all associated data, contact us. We will remove all trades, assets, and snapshots associated with your account.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Cookies</h2>
          <p>We use only essential cookies required for Firebase Authentication session management. No tracking or advertising cookies are used.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Contact</h2>
          <p>For privacy questions, contact: <a href="mailto:enkhee1117@gmail.com" className="text-indigo-400 hover:text-indigo-300">enkhee1117@gmail.com</a></p>
        </section>
      </div>
    </main>
  );
}
