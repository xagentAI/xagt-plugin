"use client";

import { useState, useCallback, useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import { useConnection, useWallet } from "@solana/wallet-adapter-react";
import { PublicKey } from "@solana/web3.js";
import { fadeUp, stagger, scaleIn } from "@/components/motion";
import {
  IconArrowLeft,
  IconArrowRight,
  IconUpload,
  IconCheck,
  IconLoader2,
  IconRocket,
  IconExternalLink,
  IconCopy,
  IconAlertCircle,
  IconChevronDown,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";
import { WalletButton } from "@/components/wallet-button";
import { createMintTransaction } from "@/lib/solana/token";
import { LAUNCHPAD_META, getLaunchpad } from "@/lib/solana/launchpad";
import { toast } from "sonner";
import {
  APP_PHASE,
  SOLANA_NETWORK,
  areEvmLaunchesEnabledOnClient,
  isMainnetLaunchAllowedOnClient,
} from "@/lib/runtime-config";
import { executeEvmLaunch } from "@/lib/evm/client";
import { InsufficientBalanceModal } from "@/components/ui/insufficient-balance-modal";

type Step = "connect" | "create" | "launchpads" | "confirm" | "success";

const stepsMeta: { id: Step; label: string; number: string }[] = [
  { id: "connect", label: "Connect", number: "01" },
  { id: "create", label: "Create Token", number: "02" },
  { id: "launchpads", label: "Launchpads", number: "03" },
  { id: "confirm", label: "Confirm", number: "04" },
];

export default function LaunchPage() {
  const router = useRouter();
  const { connection } = useConnection();
  const { publicKey, signTransaction, connected } = useWallet();
  const { session, evmAddress } = useAuth();

  const [currentStep, setCurrentStep] = useState<Step>("connect");
  const [selectedPads, setSelectedPads] = useState<string[]>([]);
  const [isDeploying, setIsDeploying] = useState(false);
  const [deployProgress, setDeployProgress] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const [decimalsOpen, setDecimalsOpen] = useState(false);

  // Result state
  const [mintAddress, setMintAddress] = useState<string | null>(null);
  const [insufficientModal, setInsufficientModal] = useState<{
    open: boolean;
    required: string;
    current: string;
    symbol: string;
    address: string | null;
  }>({
    open: false,
    required: "0.015",
    current: "0.00",
    symbol: "SOL",
    address: null,
  });
  const [mintTx, setMintTx] = useState<string | null>(null);
  const [launchResults, setLaunchResults] = useState<
    { launchpad: string; poolAddress: string; status: "live" | "failed" }[]
  >([]);

  const [tokenData, setTokenData] = useState({
    name: "",
    symbol: "",
    supply: "",
    decimals: "9",
    description: "",
  });

  const currentIndex = stepsMeta.findIndex((s) => s.id === currentStep);
  const launchRestricted = !isMainnetLaunchAllowedOnClient();
  const evmLaunchesEnabled = areEvmLaunchesEnabledOnClient();

  const isDemo = Boolean(
    session.isLoggedIn &&
      (session.walletAddress?.toLowerCase().includes("demo") ||
        (!connected && !evmAddress))
  );

  const isEvmPad = (padId: string) =>
    LAUNCHPAD_META.find((m) => m.id === padId)?.network !== "Solana";

  useEffect(() => {
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    const paramName = params.get("name");
    const paramSymbol = params.get("symbol");
    const paramSupply = params.get("supply");
    const paramDesc = params.get("desc") || params.get("description");
    if (paramName || paramSymbol) {
      setTokenData((prev) => ({
        ...prev,
        name: paramName || prev.name,
        symbol: paramSymbol || prev.symbol,
        supply: paramSupply || prev.supply || "1000000000",
        description: paramDesc || prev.description,
      }));
    }

    const resumeId = params.get("resume");
    if (!resumeId) return;

    fetch("/api/tokens")
      .then((res) => res.json())
      .then((data) => {
        const found = (data.tokens || []).find((t: any) => t.id === resumeId);
        if (found) {
          setTokenData({
            name: found.name || "",
            symbol: found.symbol || "",
            supply: found.supply ? String(found.supply) : "",
            decimals: String(found.decimals ?? "9"),
            description: found.description || "",
          });
          if (found.mint_address) {
            setMintAddress(found.mint_address);
          }
          if (found.image_url) {
            setImagePreview(found.image_url);
          }
          setCurrentStep("launchpads");
          toast.info("Resuming launch configuration for " + found.name);
        }
      })
      .catch(() => {});
  }, []);

  const handleImageSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (file.size > 5 * 1024 * 1024) {
      toast.error("Image size must be less than 5MB");
      return;
    }

    setImageFile(file);
    const reader = new FileReader();
    reader.onload = () => setImagePreview(reader.result as string);
    reader.readAsDataURL(file);
  };

  const togglePad = (padId: string) => {
    if (isEvmPad(padId) && !evmLaunchesEnabled) {
      toast.error("Multi-chain EVM launches are currently locked.");
      return;
    }

    if (isEvmPad(padId) && !evmAddress) {
      toast.error("Use an EVM wallet to launch on Four.meme and Pons.");
    }

    setSelectedPads((prev) =>
      prev.includes(padId)
        ? prev.filter((id) => id !== padId)
        : [...prev, padId]
    );
  };

  const canProceed = () => {
    switch (currentStep) {
      case "connect":
        return session.isLoggedIn;
      case "create":
        return Boolean(
          tokenData.name.trim() &&
            tokenData.symbol.trim() &&
            tokenData.supply &&
            Number(tokenData.supply) > 0
        );
      case "launchpads":
        return selectedPads.length > 0;
      case "confirm":
        return true;
      default:
        return false;
    }
  };

  const goNext = () => {
    if (currentStep === "connect") setCurrentStep("create");
    else if (currentStep === "create") setCurrentStep("launchpads");
    else if (currentStep === "launchpads") setCurrentStep("confirm");
    else if (currentStep === "confirm") handleDeploy();
  };

  const goBack = () => {
    if (currentStep === "create") setCurrentStep("connect");
    else if (currentStep === "launchpads") setCurrentStep("create");
    else if (currentStep === "confirm") setCurrentStep("launchpads");
  };

  const handleDeploy = useCallback(async () => {
    setIsDeploying(true);
    setError(null);

    try {
      if (launchRestricted && !isDemo) {
        throw new Error(
          "Mainnet launches are locked until explicitly enabled."
        );
      }

      let imageUrl: string | undefined;
      if (imageFile) {
        setDeployProgress("Uploading token asset...");
        const formData = new FormData();
        formData.append("file", imageFile);
        const uploadRes = await fetch("/api/upload", {
          method: "POST",
          body: formData,
        });
        if (uploadRes.ok) {
          const { url } = await uploadRes.json();
          imageUrl = url;
        }
      }

      let mintedTokenAddress = mintAddress;
      const requiresSolanaMint = selectedPads.some((p) => !isEvmPad(p));

      // Balance pre-flight check for Solana
      if (requiresSolanaMint && !isDemo) {
        if (!publicKey || !connection) {
          throw new Error("Solana wallet required for deployment");
        }
        try {
          const lamports = await connection.getBalance(publicKey);
          const solBal = lamports / 1e9;
          if (solBal < 0.005) {
            setInsufficientModal({
              open: true,
              required: "0.015",
              current: solBal.toFixed(4),
              symbol: "SOL",
              address: publicKey.toBase58(),
            });
            setIsDeploying(false);
            return;
          }
        } catch (balErr) {
          console.warn("[LAUNCH] Pre-flight balance check:", balErr);
        }
      }

      if (requiresSolanaMint && !mintedTokenAddress) {
        if (isDemo) {
          setDeployProgress("Minting sandbox preview token...");
          mintedTokenAddress = "mock-mint-" + Math.random().toString(36).substring(2, 9);
          setMintAddress(mintedTokenAddress);
          setMintTx("mock-tx-" + Math.random().toString(36).substring(2, 9));
        } else {
          if (!publicKey || !signTransaction || !connection) {
            throw new Error("Solana wallet required for deployment");
          }
          setDeployProgress("Compiling SPL token transaction...");
          const mintResult = await createMintTransaction(connection, publicKey, {
            name: tokenData.name,
            symbol: tokenData.symbol,
            decimals: parseInt(tokenData.decimals) || 9,
            supply: tokenData.supply,
            description: tokenData.description,
            imageUrl: imageUrl || undefined,
          });

          setDeployProgress("Sign token mint transaction...");
          const signed = await signTransaction(mintResult.transaction);
          const rawTx = signed.serialize();

          setDeployProgress("Confirming on-chain...");
          const txid = await connection.sendRawTransaction(rawTx);
          await connection.confirmTransaction(txid, "confirmed");

          mintedTokenAddress = mintResult.mintKeypair.publicKey.toBase58();
          setMintAddress(mintedTokenAddress);
          setMintTx(txid);
        }
      }

      // Record token in database
      setDeployProgress("Persisting token registry record...");
      let tokenId: string | null = null;
      try {
        const tokenRes = await fetch("/api/tokens", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: tokenData.name,
            symbol: tokenData.symbol,
            description: tokenData.description || null,
            imageUrl: imageUrl || null,
            supply: tokenData.supply,
            decimals: parseInt(tokenData.decimals),
            mintAddress: mintedTokenAddress,
          }),
        });
        if (tokenRes.ok) {
          const { token } = await tokenRes.json();
          tokenId = token.id;
        }
      } catch (err) {
        console.warn("[TOKEN] Registration non-fatal error:", err);
      }

      // Execute multi-pad launch
      const results: {
        launchpad: string;
        poolAddress: string;
        status: "live" | "failed";
      }[] = [];

      for (const padId of selectedPads) {
        const padMeta = LAUNCHPAD_META.find((m) => m.id === padId);
        setDeployProgress(`Dispatching to ${padMeta?.name || padId}...`);

        try {
          if (isDemo) {
            await new Promise((r) => setTimeout(r, 600));
            results.push({
              launchpad: padId,
              poolAddress: "mock-pool-" + Math.random().toString(36).substring(2, 8),
              status: "live",
            });
            continue;
          }

          let launchId: string | null = null;
          if (tokenId) {
            const launchRes = await fetch("/api/launches", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                tokenId,
                launchpad: padId,
                initialLiquidity: 1,
              }),
            });
            if (launchRes.ok) {
              const { launch } = await launchRes.json();
              launchId = launch.id;
            }
          }

          let launchSig = "";
          let poolAddr = "";

          if (isEvmPad(padId)) {
            if (isDemo) {
              setDeployProgress(`Simulating ${padMeta?.name || padId} sandbox deployment...`);
              await new Promise((r) => setTimeout(r, 1200));
              launchSig = "0x" + Array.from({ length: 64 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
              poolAddr = "0x" + Array.from({ length: 40 }, () => Math.floor(Math.random() * 16).toString(16)).join("");
            } else {
              if (!evmAddress) throw new Error("EVM wallet not connected");
              const evmResult = await executeEvmLaunch({
                launchpad: padId as "fourmeme" | "pons" | "sherwood",
                walletAddress: evmAddress,
                token: {
                  name: tokenData.name,
                  symbol: tokenData.symbol,
                  description: tokenData.description,
                  imageUrl: imageUrl || null,
                  supply: tokenData.supply,
                  decimals: parseInt(tokenData.decimals),
                },
              });
              launchSig = evmResult.txHash;
              poolAddr = evmResult.poolAddress;
            }
          } else {
            if (isDemo) {
              setDeployProgress(`Simulating ${padMeta?.name || padId} sandbox pool creation...`);
              await new Promise((r) => setTimeout(r, 1200));
              launchSig = "sim_solana_" + Math.random().toString(36).substring(2, 14);
              poolAddr = "sim_pool_" + Math.random().toString(36).substring(2, 14);
            } else {
              if (!connection || !publicKey || !signTransaction || !mintedTokenAddress) {
                throw new Error("Missing Solana launch prerequisites");
              }
              const service = getLaunchpad(padId);
              if (!service) {
                throw new Error(`Unsupported launchpad: ${padId}`);
              }
              const launchResult = await service.createLaunchTransaction(
                connection,
                {
                  mintAddress: new PublicKey(mintedTokenAddress),
                  walletPublicKey: publicKey,
                  initialLiquiditySol: 1,
                  tokenAmount:
                    (BigInt(tokenData.supply || "1000000000") *
                      BigInt(10 ** (parseInt(tokenData.decimals) || 9))) /
                    10n,
                }
              );

              setDeployProgress(`Sign ${padMeta?.name || padId} launch transaction...`);
              const signedLaunch = await signTransaction(launchResult.transaction);
              launchSig = await connection.sendRawTransaction(signedLaunch.serialize());
              await connection.confirmTransaction(launchSig, "confirmed");
              poolAddr = launchResult.poolAddress ? launchResult.poolAddress.toBase58() : launchSig.slice(0, 12);
            }
          }

          if (launchId) {
            await fetch("/api/launches", {
              method: "PATCH",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                launchId,
                poolAddress: poolAddr,
                launchTx: launchSig,
              }),
            });
          }

          results.push({
            launchpad: padId,
            poolAddress: poolAddr,
            status: "live",
          });
        } catch (padErr) {
          console.error(`[LAUNCH] ${padId} failed:`, padErr);
          results.push({ launchpad: padId, poolAddress: "", status: "failed" });
          toast.error(`${padMeta?.name || padId} launch failed`);
        }
      }

      setLaunchResults(results);
      setCurrentStep("success");
      toast.success("Token launched successfully!");
    } catch (err) {
      console.error("[DEPLOY] Error:", err);
      const message = err instanceof Error ? err.message : "Deployment failed";
      if (
        message.toLowerCase().includes("insufficient") ||
        message.toLowerCase().includes("debit an account") ||
        message.toLowerCase().includes("funds for rent")
      ) {
        setInsufficientModal({
          open: true,
          required: "0.015",
          current: "0.00",
          symbol: selectedPads.some((p) => !isEvmPad(p)) ? "SOL" : "BNB",
          address: publicKey ? publicKey.toBase58() : session.walletAddress,
        });
      } else {
        setError(message);
        toast.error(message);
      }
    } finally {
      setIsDeploying(false);
      setDeployProgress("");
    }
  }, [
    publicKey,
    signTransaction,
    connection,
    evmAddress,
    tokenData,
    selectedPads,
    imageFile,
    mintAddress,
    launchRestricted,
    isDemo,
  ]);

  const estimatedCost = selectedPads.reduce((total, pad) => {
    const meta = LAUNCHPAD_META.find((m) => m.id === pad);
    const feeStr = meta?.estimatedFee || "0";
    return total + parseFloat(feeStr.replace(/[^0-9.]/g, ""));
  }, 0.01);

  return (
    <div className="min-h-screen bg-[#121212] text-white">
      {/* Top navigation bar */}
      <nav className="border-b border-white/[0.06] bg-[#121212]/95 backdrop-blur-md sticky top-0 z-50 flex items-center h-16 flex-shrink-0 shrink-0">
        <div className="mx-auto max-w-[1200px] w-full px-6 md:px-10 flex items-center justify-between">
          <button
            onClick={() => {
              if (typeof window !== "undefined" && window.history.length > 1) {
                router.back();
              } else {
                router.push("/dashboard");
              }
            }}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-white/[0.05] hover:bg-white/[0.1] text-neutral-300 hover:text-white transition-colors text-xs font-sans font-medium cursor-pointer"
          >
            <IconArrowLeft size={14} />
            <span>Back</span>
          </button>
          
          <Link href="/" className="flex items-center gap-2.5">
            <div className="relative w-7 h-7 flex-shrink-0">
              <Image
                src="/logo.png"
                alt="Multipu"
                fill
                sizes="28px"
                className="object-contain"
              />
            </div>
            <span className="text-sm font-semibold text-white font-sans tracking-tight">
              Multipu
            </span>
          </Link>
          
          <div className="w-20" />
        </div>
      </nav>

      <div className="mx-auto max-w-[900px] px-6 md:px-10 py-10 md:py-14">
        {/* Step Indicator */}
        {currentStep !== "success" && (
          <motion.div
            initial="hidden"
            animate="visible"
            variants={stagger}
            className="mb-10"
          >
            <div className="flex items-center justify-center gap-2 md:gap-3 overflow-x-auto pb-2">
              {stepsMeta.map((step, i) => (
                <motion.div
                  key={step.id}
                  variants={fadeUp}
                  className="flex items-center gap-2 md:gap-3"
                >
                  <div
                    className={cn(
                      "flex items-center gap-2 px-4 py-2 rounded-full font-mono text-xs transition-colors whitespace-nowrap",
                      i === currentIndex
                        ? "bg-white text-black font-semibold"
                        : i < currentIndex
                        ? "bg-white/[0.08] text-white"
                        : "bg-[#181818] text-neutral-500 border border-white/[0.04]"
                    )}
                  >
                    <span>{step.number}</span>
                    <span className="hidden sm:inline font-sans">{step.label}</span>
                  </div>
                  {i < stepsMeta.length - 1 && (
                    <div
                      className={cn(
                        "w-6 md:w-10 h-px transition-colors",
                        i < currentIndex ? "bg-white/40" : "bg-white/[0.08]"
                      )}
                    />
                  )}
                </motion.div>
              ))}
            </div>
          </motion.div>
        )}

        {/* Error banner */}
        <AnimatePresence>
          {error && (
            <motion.div
              initial={{ opacity: 0, y: -10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              className="mb-6 p-4 rounded-xl border border-red-500/20 bg-red-500/10 flex items-start gap-3"
            >
              <IconAlertCircle
                size={16}
                className="text-red-400 mt-0.5 flex-shrink-0"
              />
              <div>
                <p className="text-xs text-red-400 font-sans font-semibold">Error</p>
                <p className="text-xs text-neutral-300 font-sans mt-0.5">{error}</p>
              </div>
              <button
                onClick={() => setError(null)}
                className="ml-auto text-neutral-400 hover:text-white text-xs font-sans cursor-pointer"
              >
                Dismiss
              </button>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Step content */}
        <AnimatePresence mode="wait">
          {/* Step 1: Connect Wallet */}
          {currentStep === "connect" && (
            <motion.div
              key="connect"
              initial="hidden"
              animate="visible"
              exit={{ opacity: 0, y: -20 }}
              variants={stagger}
              className="max-w-xl mx-auto bg-[#181818] p-8 md:p-10 rounded-2xl border border-white/[0.04]"
            >
              <motion.h1
                variants={fadeUp}
                className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans"
              >
                Connect your wallet
              </motion.h1>
              <motion.p
                variants={fadeUp}
                className="mt-2 text-sm text-neutral-400 font-sans"
              >
                Link your Solana or EVM wallet to deploy tokens and dispatch multi-venue pools.
              </motion.p>
              <motion.div
                variants={fadeUp}
                className="mt-4 inline-flex items-center gap-2 rounded-full border border-white/[0.06] bg-[#141414] px-3.5 py-1"
              >
                <span className="font-mono text-[10px] uppercase tracking-wider text-neutral-400">
                  Network
                </span>
                <span className="font-mono text-xs text-white">
                  {SOLANA_NETWORK}
                </span>
                <span className="text-neutral-600">/</span>
                <span className="font-mono text-xs text-white">
                  {APP_PHASE}
                </span>
              </motion.div>

              <motion.div variants={fadeUp} className="mt-8 space-y-4">
                {!session.isLoggedIn ? (
                  <div className="p-8 rounded-xl border border-white/[0.04] bg-[#141414] text-center space-y-4">
                    <p className="text-xs text-neutral-400 font-sans">
                      Connect and authenticate your wallet to continue.
                    </p>
                    <WalletButton />
                  </div>
                ) : (
                  <div className="p-5 rounded-xl border border-emerald-500/30 bg-emerald-500/5">
                    <div className="flex items-center gap-3">
                      <div className="w-2.5 h-2.5 rounded-full bg-emerald-400 animate-pulse" />
                      <span className="font-mono text-xs text-white">
                        {session.walletAddress.slice(0, 6)}...
                        {session.walletAddress.slice(-4)}
                      </span>
                      <span className="font-mono text-xs text-emerald-400 ml-auto">
                        {isDemo ? "Demo Session Ready" : "Connected & Authenticated"}
                      </span>
                      <IconCheck size={16} className="text-emerald-400" />
                    </div>
                  </div>
                )}
              </motion.div>
            </motion.div>
          )}

          {/* Step 2: Create Token */}
          {currentStep === "create" && (
            <motion.div
              key="create"
              initial="hidden"
              animate="visible"
              exit={{ opacity: 0, y: -20 }}
              variants={stagger}
              className="max-w-xl mx-auto bg-[#181818] p-8 md:p-10 rounded-2xl border border-white/[0.04]"
            >
              <motion.h1
                variants={fadeUp}
                className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans"
              >
                Create your token
              </motion.h1>
              <motion.p
                variants={fadeUp}
                className="mt-2 text-sm text-neutral-400 font-sans"
              >
                Define your token&apos;s identity and supply parameters.
              </motion.p>

              <motion.div variants={fadeUp} className="mt-8 space-y-5">
                {/* Token image upload */}
                <div className="flex items-center gap-5">
                  <label className="relative w-20 h-20 border border-dashed border-white/[0.1] hover:border-white/30 bg-[#141414] rounded-2xl flex flex-col items-center justify-center gap-1 transition-colors cursor-pointer overflow-hidden flex-shrink-0">
                    {imagePreview ? (
                      <Image
                        src={imagePreview}
                        alt="Token logo"
                        fill
                        className="object-cover"
                      />
                    ) : (
                      <>
                        <IconUpload size={18} className="text-neutral-400" />
                        <span className="text-[10px] font-mono text-neutral-500">
                          Logo
                        </span>
                      </>
                    )}
                    <input
                      type="file"
                      accept="image/png,image/jpeg,image/webp,image/gif"
                      className="absolute inset-0 opacity-0 cursor-pointer"
                      onChange={handleImageSelect}
                    />
                  </label>
                  <div className="flex-1">
                    <label className="font-sans text-xs font-medium text-neutral-300 block mb-2">
                      Token Name
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. MoonCoin"
                      maxLength={32}
                      value={tokenData.name}
                      onChange={(e) =>
                        setTokenData({ ...tokenData, name: e.target.value })
                      }
                      className="w-full bg-[#141414] border border-white/[0.08] focus:border-white/30 rounded-xl px-4 py-3 text-sm text-white placeholder:text-neutral-500 font-mono transition-colors focus:outline-none"
                    />
                  </div>
                </div>

                {/* Symbol + Supply */}
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="font-sans text-xs font-medium text-neutral-300 block mb-2">
                      Symbol
                    </label>
                    <input
                      type="text"
                      placeholder="e.g. MOON"
                      maxLength={10}
                      value={tokenData.symbol}
                      onChange={(e) =>
                        setTokenData({
                          ...tokenData,
                          symbol: e.target.value.toUpperCase(),
                        })
                      }
                      className="w-full bg-[#141414] border border-white/[0.08] focus:border-white/30 rounded-xl px-4 py-3 text-sm text-white placeholder:text-neutral-500 font-mono transition-colors focus:outline-none uppercase"
                    />
                  </div>
                  <div>
                    <label className="font-sans text-xs font-medium text-neutral-300 block mb-2">
                      Total Supply
                    </label>
                    <input
                      type="text"
                      inputMode="numeric"
                      placeholder="e.g. 1000000000"
                      value={tokenData.supply}
                      onChange={(e) => {
                        const val = e.target.value.replace(/[^0-9]/g, "");
                        setTokenData({ ...tokenData, supply: val });
                      }}
                      className="w-full bg-[#141414] border border-white/[0.08] focus:border-white/30 rounded-xl px-4 py-3 text-sm text-white placeholder:text-neutral-500 font-mono transition-colors focus:outline-none"
                    />
                  </div>
                </div>

                {/* Custom Decimals Dropdown */}
                <div>
                  <label className="font-sans text-xs font-medium text-neutral-300 block mb-2">
                    Decimals
                  </label>
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setDecimalsOpen(!decimalsOpen)}
                      className="w-full bg-[#141414] border border-white/[0.08] hover:border-white/20 focus:border-white/30 rounded-xl px-4 py-3 text-sm text-white transition-colors flex items-center justify-between font-mono cursor-pointer"
                    >
                      <span>{tokenData.decimals} decimals</span>
                      <IconChevronDown
                        size={16}
                        className={cn("text-neutral-400 transition-transform duration-200", decimalsOpen && "rotate-180")}
                      />
                    </button>
                    <AnimatePresence>
                      {decimalsOpen && (
                        <motion.div
                          initial={{ opacity: 0, y: -4 }}
                          animate={{ opacity: 1, y: 0 }}
                          exit={{ opacity: 0, y: -4 }}
                          className="absolute left-0 right-0 top-full mt-2 z-50 bg-[#181818] border border-white/[0.1] rounded-xl p-1.5 space-y-1 shadow-2xl"
                        >
                          {[6, 8, 9].map((d) => (
                            <button
                              key={d}
                              type="button"
                              onClick={() => {
                                setTokenData({ ...tokenData, decimals: String(d) });
                                setDecimalsOpen(false);
                              }}
                              className={cn(
                                "w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-xs font-mono transition-colors cursor-pointer",
                                tokenData.decimals === String(d)
                                  ? "bg-white/[0.1] text-white font-semibold"
                                  : "text-neutral-400 hover:text-white hover:bg-white/[0.04]"
                              )}
                            >
                              <span>{d} decimals</span>
                              {tokenData.decimals === String(d) && <IconCheck size={14} className="text-white" />}
                            </button>
                          ))}
                        </motion.div>
                      )}
                    </AnimatePresence>
                  </div>
                </div>

                {/* Description */}
                <div>
                  <label className="font-sans text-xs font-medium text-neutral-300 block mb-2">
                    Description
                  </label>
                  <textarea
                    placeholder="A short description of your token..."
                    maxLength={500}
                    value={tokenData.description}
                    onChange={(e) =>
                      setTokenData({
                        ...tokenData,
                        description: e.target.value,
                      })
                    }
                    rows={3}
                    className="w-full bg-[#141414] border border-white/[0.08] focus:border-white/30 rounded-xl px-4 py-3 text-sm text-white placeholder:text-neutral-500 font-sans transition-colors resize-none focus:outline-none"
                  />
                  <div className="text-right mt-1">
                    <span className="font-mono text-[10px] text-neutral-500">
                      {tokenData.description.length}/500
                    </span>
                  </div>
                </div>
              </motion.div>
            </motion.div>
          )}

          {/* Step 3: Select Launchpads */}
          {currentStep === "launchpads" && (
            <motion.div
              key="launchpads"
              initial="hidden"
              animate="visible"
              exit={{ opacity: 0, y: -20 }}
              variants={stagger}
              className="max-w-3xl mx-auto bg-[#181818] p-8 md:p-10 rounded-2xl border border-white/[0.04]"
            >
              <motion.h1
                variants={fadeUp}
                className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans"
              >
                Select launchpads
              </motion.h1>
              <motion.p
                variants={fadeUp}
                className="mt-2 text-sm text-neutral-400 font-sans"
              >
                Choose one or more platforms. Multipu automatically orchestrates simultaneous deployment.
              </motion.p>

              <motion.div
                variants={fadeUp}
                className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-4"
              >
                {LAUNCHPAD_META.map((pad) => (
                  <button
                    key={pad.id}
                    onClick={() => togglePad(pad.id)}
                    className={cn(
                      "relative text-left p-5 rounded-2xl border transition-all group cursor-pointer flex flex-col justify-between min-h-[180px]",
                      selectedPads.includes(pad.id)
                        ? "border-white/40 bg-[#161616]"
                        : pad.ready
                        ? "border-white/[0.04] bg-[#141414] hover:bg-[#161616] hover:border-white/[0.08]"
                        : "border-white/[0.02] bg-[#141414] opacity-50 cursor-not-allowed"
                    )}
                  >
                    {selectedPads.includes(pad.id) && (
                      <div className="absolute top-4 right-4 w-5 h-5 rounded-full bg-white text-black flex items-center justify-center">
                        <IconCheck size={12} strokeWidth={3} />
                      </div>
                    )}

                    <div>
                      <div className="flex items-center gap-3 mb-3">
                        <div className="relative w-10 h-10 rounded-xl overflow-hidden bg-black/40 border border-white/[0.06] flex-shrink-0">
                          <Image
                            src={pad.image}
                            alt={pad.name}
                            fill
                            className="object-cover"
                          />
                        </div>
                        <div>
                          <h3 className="text-sm font-semibold text-white font-sans">
                            {pad.name}
                          </h3>
                          <span className="font-mono text-[10px] text-neutral-400 block">
                            Est. fee: {pad.estimatedFee}
                          </span>
                          <span className="font-mono text-[10px] text-neutral-500 block">
                            {pad.network}
                          </span>
                        </div>
                      </div>
                      <p className="text-xs text-neutral-400 font-sans leading-relaxed">
                        {pad.description}
                      </p>
                    </div>

                    {!pad.ready && (
                      <span className="text-[10px] font-mono text-neutral-500 uppercase tracking-wider block mt-3">
                        Coming soon
                      </span>
                    )}
                  </button>
                ))}
              </motion.div>

              {selectedPads.length > 0 && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="mt-6 p-4 rounded-xl border border-white/[0.04] bg-[#141414]"
                >
                  <div className="flex items-center justify-between text-xs font-mono">
                    <span className="text-neutral-400">
                      Selected:{" "}
                      {selectedPads
                        .map(
                          (p) =>
                            LAUNCHPAD_META.find((m) => m.id === p)?.name || p
                        )
                        .join(", ")}
                    </span>
                    <span className="text-white font-semibold">
                      {selectedPads.length === 1
                        ? "Single launch"
                        : selectedPads.length === 2
                        ? "Dual launch"
                        : `${selectedPads.length}-venue launch`}
                    </span>
                  </div>
                </motion.div>
              )}
            </motion.div>
          )}

          {/* Step 4: Confirm */}
          {currentStep === "confirm" && (
            <motion.div
              key="confirm"
              initial="hidden"
              animate="visible"
              exit={{ opacity: 0, y: -20 }}
              variants={stagger}
              className="max-w-xl mx-auto bg-[#181818] p-8 md:p-10 rounded-2xl border border-white/[0.04]"
            >
              <motion.h1
                variants={fadeUp}
                className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans"
              >
                Confirm &amp; launch
              </motion.h1>
              <motion.p
                variants={fadeUp}
                className="mt-2 text-sm text-neutral-400 font-sans"
              >
                Review parameters and initiate simultaneous protocol deployment.
              </motion.p>

              <motion.div
                variants={fadeUp}
                className="mt-8 rounded-2xl border border-white/[0.04] bg-[#141414] divide-y divide-white/[0.04] overflow-hidden"
              >
                {launchRestricted && !isDemo && (
                  <div className="p-5 bg-red-500/10 border-b border-red-500/20">
                    <p className="text-xs text-red-400 font-semibold font-sans">
                      Mainnet safety lock is enabled
                    </p>
                    <p className="text-xs text-neutral-300 font-sans mt-1">
                      This deployment only allows testnet-phase usage until mainnet is explicitly configured.
                    </p>
                  </div>
                )}
                {isDemo && (
                  <div className="p-4 bg-emerald-500/10 border-b border-emerald-500/20 flex items-center justify-between">
                    <span className="font-mono text-xs text-emerald-400 font-medium">
                      Demo Simulation Mode
                    </span>
                    <span className="text-xs text-neutral-400 font-sans">
                      Sandbox testnet launch preview
                    </span>
                  </div>
                )}
                <div className="p-6">
                  <span className="font-mono text-[10px] text-neutral-500 uppercase tracking-widest block mb-4">
                    Token Details
                  </span>
                  <div className="space-y-3">
                    {[
                      { label: "Name", value: tokenData.name || "-" },
                      { label: "Symbol", value: tokenData.symbol || "-" },
                      {
                        label: "Supply",
                        value: tokenData.supply
                          ? Number(tokenData.supply).toLocaleString()
                          : "-",
                      },
                      { label: "Decimals", value: tokenData.decimals },
                      {
                        label: "Image",
                        value: imageFile ? imageFile.name : "None",
                      },
                    ].map((row) => (
                      <div
                        key={row.label}
                        className="flex items-center justify-between text-xs"
                      >
                        <span className="text-neutral-400 font-sans">
                          {row.label}
                        </span>
                        <span className="font-mono text-white font-medium">
                          {row.value}
                        </span>
                      </div>
                    ))}
                  </div>
                </div>

                <div className="p-6">
                  <span className="font-mono text-[10px] text-neutral-500 uppercase tracking-widest block mb-3">
                    Selected Venues
                  </span>
                  <div className="flex flex-wrap gap-2">
                    {selectedPads.map((padId) => {
                      const meta = LAUNCHPAD_META.find((m) => m.id === padId);
                      return (
                        <span
                          key={padId}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-mono rounded-full bg-white/[0.05] border border-white/[0.06] text-white"
                        >
                          <IconRocket size={12} className="text-neutral-400" />
                          {meta?.name || padId}
                        </span>
                      );
                    })}
                  </div>
                </div>

                <div className="p-6">
                  <div className="flex items-center justify-between">
                    <span className="text-xs text-neutral-400 font-sans">
                      Estimated Cost (Mint + Gas)
                    </span>
                    <span className="text-base font-mono font-bold text-white">
                      ~{estimatedCost.toFixed(2)} SOL
                    </span>
                  </div>
                </div>
              </motion.div>

              {isDeploying && deployProgress && (
                <motion.div
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  className="mt-6 p-4 rounded-xl border border-white/[0.08] bg-[#141414]"
                >
                  <div className="flex items-center gap-3">
                    <IconLoader2 size={16} className="text-white animate-spin" />
                    <span className="text-xs text-white font-mono">
                      {deployProgress}
                    </span>
                  </div>
                </motion.div>
              )}
            </motion.div>
          )}

          {/* Step 5: Success */}
          {currentStep === "success" && (
            <motion.div
              key="success"
              initial="hidden"
              animate="visible"
              variants={stagger}
              className="max-w-xl mx-auto bg-[#181818] p-8 md:p-10 rounded-2xl border border-white/[0.04] text-center"
            >
              <motion.div variants={scaleIn} className="mb-6">
                <div className="inline-flex w-16 h-16 rounded-full bg-emerald-500/10 border border-emerald-500/20 items-center justify-center text-emerald-400">
                  <IconCheck size={30} />
                </div>
              </motion.div>

              <motion.h1
                variants={fadeUp}
                className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans"
              >
                Token launched!
              </motion.h1>
              <motion.p
                variants={fadeUp}
                className="mt-2 text-sm text-neutral-400 font-sans"
              >
                Your token has been deployed and dispatched to{" "}
                {launchResults.filter((r) => r.status === "live").length}{" "}
                launchpad
                {launchResults.filter((r) => r.status === "live").length !== 1
                  ? "s"
                  : ""}
                .
              </motion.p>

              {mintAddress && (
                <motion.div
                  variants={fadeUp}
                  className="mt-6 p-4 rounded-xl border border-white/[0.04] bg-[#141414] text-left"
                >
                  <span className="font-mono text-[10px] text-neutral-500 uppercase tracking-widest block mb-2">
                    Token Address
                  </span>
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-mono text-xs text-white truncate select-all">
                      {mintAddress}
                    </span>
                    <button
                      onClick={() => {
                        navigator.clipboard.writeText(mintAddress);
                        toast.success("Copied to clipboard!");
                      }}
                      className="text-neutral-400 hover:text-white transition-colors p-1"
                    >
                      <IconCopy size={14} />
                    </button>
                  </div>
                  {mintTx && (
                    <a
                      href={`https://explorer.solana.com/tx/${mintTx}?cluster=${process.env.NEXT_PUBLIC_SOLANA_NETWORK || "devnet"}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-2 inline-flex items-center gap-1 text-xs font-mono text-neutral-400 hover:text-white transition-colors"
                    >
                      <span>View transaction</span>
                      <IconExternalLink size={12} />
                    </a>
                  )}
                </motion.div>
              )}

              <motion.div variants={fadeUp} className="mt-4 space-y-2">
                {launchResults.map((result) => {
                  const meta = LAUNCHPAD_META.find(
                    (m) => m.id === result.launchpad
                  );
                  return (
                    <div
                      key={result.launchpad}
                      className="flex items-center justify-between p-3.5 rounded-xl border border-white/[0.04] bg-[#141414]"
                    >
                      <div className="flex items-center gap-3">
                        <span
                          className={cn(
                            "w-2 h-2 rounded-full",
                            result.status === "live"
                              ? "bg-emerald-400"
                              : "bg-red-400"
                          )}
                        />
                        <span className="text-xs font-semibold text-white font-sans">
                          {meta?.name || result.launchpad}
                        </span>
                      </div>
                      <span
                        className={cn(
                          "font-mono text-xs font-semibold",
                          result.status === "live"
                            ? "text-emerald-400"
                            : "text-red-400"
                        )}
                      >
                        {result.status === "live" ? "Live" : "Failed"}
                      </span>
                    </div>
                  );
                })}
              </motion.div>

              <motion.div
                variants={fadeUp}
                className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-3"
              >
                <Link
                  href="/dashboard"
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3 text-xs sm:text-sm font-semibold bg-white text-black hover:bg-neutral-200 rounded-full transition-colors font-sans"
                >
                  <span>View Dashboard</span>
                  <IconArrowRight size={15} />
                </Link>
                <button
                  onClick={() => {
                    setCurrentStep("connect");
                    setSelectedPads([]);
                    setTokenData({
                      name: "",
                      symbol: "",
                      supply: "",
                      decimals: "9",
                      description: "",
                    });
                    setImageFile(null);
                    setImagePreview(null);
                    setMintAddress(null);
                    setMintTx(null);
                    setLaunchResults([]);
                    setError(null);
                  }}
                  className="w-full sm:w-auto inline-flex items-center justify-center gap-2 px-6 py-3 text-xs sm:text-sm font-medium text-white bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.06] rounded-full transition-colors font-sans cursor-pointer"
                >
                  Launch Another
                </button>
              </motion.div>
            </motion.div>
          )}
        </AnimatePresence>

        {/* Navigation buttons */}
        {currentStep !== "success" && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            className="max-w-xl mx-auto mt-8 flex items-center justify-between"
          >
            <button
              onClick={goBack}
              disabled={currentStep === "connect"}
              className={cn(
                "inline-flex items-center gap-2 px-5 py-2.5 text-xs font-sans font-medium rounded-full transition-colors cursor-pointer",
                currentStep === "connect"
                  ? "opacity-30 cursor-not-allowed bg-white/[0.02] text-neutral-500"
                  : "bg-white/[0.05] hover:bg-white/[0.1] text-white border border-white/[0.06]"
              )}
            >
              <IconArrowLeft size={14} />
              <span>Back</span>
            </button>
            <button
              onClick={goNext}
              disabled={!canProceed() || isDeploying}
              className={cn(
                "inline-flex items-center gap-2 px-6 py-2.5 text-xs font-sans font-semibold rounded-full transition-colors cursor-pointer",
                canProceed() && !isDeploying
                  ? "bg-white text-black hover:bg-neutral-200"
                  : "bg-white/[0.1] text-neutral-500 cursor-not-allowed"
              )}
            >
              {isDeploying ? (
                <>
                  <IconLoader2 size={14} className="animate-spin" />
                  <span>Deploying...</span>
                </>
              ) : currentStep === "confirm" ? (
                <>
                  <IconRocket size={14} />
                  <span>Deploy &amp; Launch</span>
                </>
              ) : (
                <>
                  <span>Next</span>
                  <IconArrowRight size={14} />
                </>
              )}
            </button>
          </motion.div>
        )}
      </div>

      <InsufficientBalanceModal
        isOpen={insufficientModal.open}
        onClose={() => setInsufficientModal((prev) => ({ ...prev, open: false }))}
        requiredAmount={insufficientModal.required}
        currentBalance={insufficientModal.current}
        symbol={insufficientModal.symbol}
        walletAddress={insufficientModal.address}
        actionName="token deployment"
      />
    </div>
  );
}
