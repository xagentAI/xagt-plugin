import type { NextConfig } from 'next';

const nextConfig: NextConfig = {
  // Next writes editor-assistant rule files into the project root on `dev` unless this
  // is off. They are not part of the product and should not appear in the repository.
  agentRules: false,

  // `dev` refuses cross-origin requests for its own HMR assets, which silently breaks
  // hydration when the app is opened on the loopback address rather than `localhost`.
  allowedDevOrigins: ['127.0.0.1'],

  // The deployment-proof document must live at the literal well-known path on the
  // same origin as the API. Next cannot route a directory beginning with a dot,
  // so it is served by a normal route handler and rewritten into place.
  async rewrites() {
    return [
      {
        source: '/.well-known/xagent-verification.json',
        destination: '/api/xagent-verification',
      },
    ];
  },
};

export default nextConfig;
