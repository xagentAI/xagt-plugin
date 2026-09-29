import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const portfolioTarget = process.env.VITE_PORTFOLIO_API_URL || "http://127.0.0.1:8044";
const accountBindingTarget = process.env.VITE_ACCOUNT_BINDING_API_URL || "http://127.0.0.1:8047";
const coreFundingTarget = process.env.VITE_CORE_FUNDING_API_URL || "http://127.0.0.1:8018";
const depositWalletTarget = process.env.VITE_DEPOSIT_WALLET_API_URL || "http://127.0.0.1:8048";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": {
        target: portfolioTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
      "/account-api": {
        target: accountBindingTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/account-api/, ""),
      },
      "/core-funding-api": {
        target: coreFundingTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/core-funding-api/, ""),
      },
      "/deposit-wallet-api": {
        target: depositWalletTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/deposit-wallet-api/, ""),
      },
    },
  },
});
