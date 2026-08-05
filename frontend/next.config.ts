import type { NextConfig } from "next";
import { securityHeaderRules } from "./src/lib/security-headers";

const nextConfig: NextConfig = {
  // Self-contained server bundle for the Docker image (frontend/Dockerfile).
  output: "standalone",
  // Version and framework disclosure buys an attacker a CVE list for free.
  poweredByHeader: false,
  async headers() {
    return securityHeaderRules();
  },
};

export default nextConfig;
