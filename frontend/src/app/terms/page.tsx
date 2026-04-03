"use client";

export default function TermsPage() {
  return (
    <main className="min-h-screen bg-gray-900 text-gray-100 p-8 font-sans">
      <div className="max-w-3xl mx-auto space-y-6">
        <h1 className="text-2xl font-bold text-white">Terms of Service</h1>
        <p className="text-sm text-gray-400">Last updated: April 2026</p>

        <section className="space-y-3 text-gray-300 text-sm leading-relaxed">
          <h2 className="text-lg font-semibold text-white mt-6">Service Description</h2>
          <p>Portfolio Tracker is a personal portfolio management tool that helps you track trades, positions, and investment themes. It is not a brokerage, financial advisor, or trading platform.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Not Financial Advice</h2>
          <p className="font-medium text-amber-300">This application is for informational and tracking purposes only. Nothing in this application constitutes financial, investment, tax, or legal advice. All investment decisions are your own. Past performance does not guarantee future results.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Data Accuracy</h2>
          <p>Stock prices are sourced from Yahoo Finance and may be delayed or inaccurate. Portfolio values, P&amp;L calculations, and RSI indicators are estimates based on the data you provide. We do not guarantee the accuracy of any calculation. Always verify with your brokerage statements.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Your Responsibilities</h2>
          <ul className="list-disc list-inside space-y-1">
            <li>You are responsible for the accuracy of trade data you enter</li>
            <li>You are responsible for maintaining backups of your data</li>
            <li>You must not use the service for illegal purposes</li>
            <li>You must not attempt to access other users' data</li>
          </ul>

          <h2 className="text-lg font-semibold text-white mt-6">Service Availability</h2>
          <p>We provide the service on a best-effort basis. We may modify, suspend, or discontinue the service at any time. We are not liable for any loss of data or service interruptions.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Limitation of Liability</h2>
          <p>The service is provided "as is" without warranties of any kind. We are not responsible for investment losses, tax consequences, or any damages arising from use of this application.</p>

          <h2 className="text-lg font-semibold text-white mt-6">Contact</h2>
          <p>For questions about these terms, contact: <a href="mailto:enkhee1117@gmail.com" className="text-indigo-400 hover:text-indigo-300">enkhee1117@gmail.com</a></p>
        </section>
      </div>
    </main>
  );
}
