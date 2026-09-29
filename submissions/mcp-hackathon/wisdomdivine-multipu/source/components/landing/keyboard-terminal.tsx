"use client";

import Link from "next/link";
import { motion, fadeUp, stagger, scaleIn } from "@/components/motion";

export function KeyboardTerminal() {
  return (
    <motion.section
      id="terminal"
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-80px" }}
      variants={stagger}
      className="py-16 sm:py-24 md:py-36 px-4 sm:px-6 md:px-12 max-w-[1360px] mx-auto scroll-mt-24"
    >
      {/* Outer Forest Green Container matching Screenshot 3 */}
      <motion.div variants={fadeUp} className="rounded-3xl sm:rounded-[40px] bg-[#1a2d24] text-white p-6 sm:p-10 md:p-14 lg:p-20 overflow-hidden flex flex-col items-center">
        {/* Header Text */}
        <motion.div variants={fadeUp} className="text-center max-w-2xl mb-8 sm:mb-12">
          <div className="text-xs font-mono uppercase tracking-widest text-[#fbc5b3] mb-3">
            Developer Controls &amp; Terminal Hotkeys
          </div>
          <h2 className="text-2xl sm:text-4xl md:text-5xl font-normal tracking-tight text-white mb-3 sm:mb-4">
            Engineered for high-speed algorithmic execution
          </h2>
          <p className="text-xs sm:text-sm text-neutral-300 leading-relaxed">
            Use high-performance SDK commands or keyboard-driven terminal hotkeys to swap, launch, and rebalance liquidity in milliseconds.
          </p>
        </motion.div>

        {/* Technical Mechanical Keyboard Wireframe SVG matching Screenshot 3 */}
        <motion.div variants={scaleIn} className="w-full max-w-4xl overflow-x-auto py-6 flex justify-center">
          <svg
            viewBox="0 0 960 440"
            className="w-full max-w-[900px] h-auto text-[#fbc5b3] stroke-current fill-none"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            {/* Outer Case Bezel */}
            <rect
              x="20"
              y="20"
              width="920"
              height="400"
              rx="24"
              className="stroke-[#fbc5b3]/40 fill-[#162720]/60"
              strokeWidth="2"
            />
            {/* Power indicator toggle at top right */}
            <rect x="850" y="14" width="30" height="6" rx="3" className="fill-[#fbc5b3]" />

            {/* Function Row */}
            <g className="stroke-[#fbc5b3]/30">
              {/* Esc */}
              <rect x="35" y="35" width="50" height="48" rx="8" />
              <text x="43" y="65" className="fill-[#fbc5b3] stroke-none text-[11px] font-mono">esc</text>
              {/* F1 - F12 */}
              {Array.from({ length: 12 }).map((_, i) => (
                <g key={i}>
                  <rect x={100 + i * 58} y="35" width="50" height="48" rx="8" />
                  <text
                    x={116 + i * 58}
                    y="65"
                    className="fill-[#fbc5b3]/60 stroke-none text-[10px] font-mono"
                  >
                    F{i + 1}
                  </text>
                </g>
              ))}
              {/* Del / Top Right */}
              <rect x={810} y="35" width="115" height="48" rx="8" />
            </g>

            {/* Number Row */}
            <g className="stroke-[#fbc5b3]/30">
              <rect x="35" y="93" width="52" height="50" rx="8" />
              {/* Highlight Keycap 1: 7-Dot Cluster Icon (Peach filled) */}
              <rect x="95" y="93" width="52" height="50" rx="8" className="stroke-none fill-[#fbc5b3]" />
              <g className="fill-[#1a2d24] stroke-none">
                <circle cx="121" cy="118" r="4" />
                <circle cx="111" cy="111" r="3.5" />
                <circle cx="131" cy="111" r="3.5" />
                <circle cx="111" cy="125" r="3.5" />
                <circle cx="131" cy="125" r="3.5" />
                <circle cx="121" cy="105" r="3.5" />
                <circle cx="121" cy="131" r="3.5" />
              </g>

              {Array.from({ length: 11 }).map((_, i) => (
                <rect key={i} x={155 + i * 58} y="93" width="50" height="50" rx="8" />
              ))}
              {/* Backspace */}
              <rect x={793} y="93" width="132" height="50" rx="8" />
              <text x={895} y="123" className="fill-[#fbc5b3] stroke-none text-sm font-mono">←</text>
            </g>

            {/* QWERTY Row */}
            <g className="stroke-[#fbc5b3]/30">
              {/* Tab */}
              <rect x="35" y="153" width="76" height="50" rx="8" />
              <text x="45" y="183" className="fill-[#fbc5b3] stroke-none text-xs font-mono">→</text>

              {Array.from({ length: 11 }).map((_, i) => (
                <g key={i}>
                  {/* Highlight Keycap 2 at position 7: Radial Dot Cluster */}
                  {i === 7 ? (
                    <g>
                      <rect x={119 + i * 58} y="153" width="50" height="50" rx="8" className="stroke-none fill-[#fbc5b3]" />
                      <g className="fill-[#1a2d24] stroke-none">
                        <circle cx={144 + i * 58} cy="178" r="3" />
                        {Array.from({ length: 8 }).map((_, r) => {
                          const angle = (r * Math.PI) / 4;
                          return (
                            <circle
                              key={r}
                              cx={144 + i * 58 + Math.cos(angle) * 11}
                              cy={178 + Math.sin(angle) * 11}
                              r="2.2"
                            />
                          );
                        })}
                      </g>
                    </g>
                  ) : (
                    <rect x={119 + i * 58} y="153" width="50" height="50" rx="8" />
                  )}
                </g>
              ))}

              {/* Highlight Keycap 3 at right: Concentric Radar/Antenna symbol */}
              <rect x="757" y="153" width="50" height="50" rx="8" className="stroke-none fill-[#fbc5b3]" />
              <g className="stroke-[#1a2d24] stroke-[2] fill-none">
                <circle cx="782" cy="182" r="3" className="fill-[#1a2d24]" />
                <path d="M774,180 A10,10 0 0,1 790,180" />
                <path d="M770,175 A15,15 0 0,1 794,175" />
                <path d="M766,170 A20,20 0 0,1 798,170" />
              </g>

              {/* Enter shape */}
              <path
                d="M815,153 L925,153 L925,263 L865,263 L865,203 L815,203 Z"
                rx="8"
                className="stroke-[#fbc5b3]/40"
              />
              <text x="880" y="215" className="fill-[#fbc5b3] stroke-none text-base font-mono">↵</text>
            </g>

            {/* ASDF / Caps Row */}
            <g className="stroke-[#fbc5b3]/30">
              {/* Caps */}
              <rect x="35" y="213" width="95" height="50" rx="8" />
              <text x="45" y="243" className="fill-[#fbc5b3] stroke-none text-xs font-mono">⇧</text>

              {/* Highlight Keycap 4: Radiating Sunburst / Star Asterisk */}
              <rect x="138" y="213" width="50" height="50" rx="8" />
              <rect x="196" y="213" width="50" height="50" rx="8" className="stroke-none fill-[#fbc5b3]" />
              <g className="stroke-[#1a2d24] stroke-[2] fill-none">
                {Array.from({ length: 16 }).map((_, s) => {
                  const angle = (s * Math.PI) / 8;
                  return (
                    <line
                      key={s}
                      x1={221 + Math.cos(angle) * 4}
                      y1={238 + Math.sin(angle) * 4}
                      x2={221 + Math.cos(angle) * 13}
                      y2={238 + Math.sin(angle) * 13}
                    />
                  );
                })}
              </g>

              {Array.from({ length: 9 }).map((_, i) => (
                <rect key={i} x={254 + i * 58} y="213" width="50" height="50" rx="8" />
              ))}
              <rect x="776" y="213" width="81" height="50" rx="8" />
            </g>

            {/* Bottom Spacebar & Modifier Row */}
            <g className="stroke-[#fbc5b3]/30">
              <rect x="35" y="273" width="125" height="50" rx="8" />
              <text x="45" y="303" className="fill-[#fbc5b3] stroke-none text-xs font-mono">⇧</text>
              {Array.from({ length: 9 }).map((_, i) => (
                <rect key={i} x={168 + i * 58} y="273" width="50" height="50" rx="8" />
              ))}

              {/* Highlight Keycap 5: Half Moon / Phase Contrast Symbol */}
              <rect x="690" y="273" width="50" height="50" rx="8" className="stroke-none fill-[#fbc5b3]" />
              <g className="fill-[#1a2d24] stroke-none">
                <circle cx="715" cy="298" r="11" />
                <path d="M715,287 A11,11 0 0,0 715,309 Z" className="fill-[#fbc5b3]" />
              </g>

              <rect x="748" y="273" width="177" height="50" rx="8" />
              <text x="900" y="303" className="fill-[#fbc5b3] stroke-none text-xs font-mono">⇧</text>
            </g>

            {/* Bottom Row */}
            <g className="stroke-[#fbc5b3]/30">
              <rect x="35" y="333" width="55" height="50" rx="8" />
              <text x="45" y="363" className="fill-[#fbc5b3] stroke-none text-[10px] font-mono">fn</text>

              <rect x="98" y="333" width="55" height="50" rx="8" />
              <text x="105" y="363" className="fill-[#fbc5b3] stroke-none text-[9px] font-mono">control</text>

              <rect x="161" y="333" width="55" height="50" rx="8" />
              <text x="170" y="363" className="fill-[#fbc5b3] stroke-none text-[9px] font-mono">option</text>

              <rect x="224" y="333" width="65" height="50" rx="8" />
              <text x="230" y="363" className="fill-[#fbc5b3] stroke-none text-[9px] font-mono">command</text>

              {/* Wide Spacebar */}
              <rect x="297" y="333" width="280" height="50" rx="8" />

              <rect x="585" y="333" width="65" height="50" rx="8" />
              <text x="591" y="363" className="fill-[#fbc5b3] stroke-none text-[9px] font-mono">command</text>

              {/* Arrow Keys Cluster */}
              <rect x="658" y="333" width="46" height="50" rx="8" />
              <text x="675" y="363" className="fill-[#fbc5b3] stroke-none text-xs font-mono">◀</text>

              <g>
                <rect x="712" y="333" width="48" height="23" rx="4" />
                <text x="730" y="350" className="fill-[#fbc5b3] stroke-none text-[9px] font-mono">▲</text>
                <rect x="712" y="360" width="48" height="23" rx="4" />
                <text x="730" y="376" className="fill-[#fbc5b3] stroke-none text-[9px] font-mono">▼</text>
              </g>

              <rect x="768" y="333" width="46" height="50" rx="8" />
              <text x="785" y="363" className="fill-[#fbc5b3] stroke-none text-xs font-mono">▶</text>
            </g>
          </svg>
        </motion.div>

        {/* Action buttons */}
        <motion.div variants={stagger} className="flex flex-col sm:flex-row flex-wrap items-stretch sm:items-center justify-center gap-3 sm:gap-4 mt-8 w-full sm:w-auto">
          <motion.a
            variants={fadeUp}
            href="https://docs.multipu.fun"
            target="_blank"
            rel="noopener noreferrer"
            className="px-8 py-3 rounded-full bg-white text-[#1a2d24] font-mono text-xs font-semibold hover:bg-[#fbc5b3] transition-colors cursor-pointer inline-flex items-center justify-center gap-1.5 hover:scale-105 active:scale-95 duration-200 text-center"
          >
            <span>API Documentation</span>
            <span className="text-[10px]">↗</span>
          </motion.a>
          <motion.div variants={fadeUp} className="w-full sm:w-auto">
            <Link
              href="/dashboard/api"
              className="w-full sm:w-auto block text-center px-8 py-3 rounded-full bg-[#fbc5b3] text-[#1a2d24] font-mono text-xs font-semibold hover:bg-white transition-colors cursor-pointer hover:scale-105 active:scale-95 duration-200"
            >
              Developer API Keys
            </Link>
          </motion.div>
          <motion.div variants={fadeUp} className="w-full sm:w-auto">
            <Link
              href="/dashboard"
              className="w-full sm:w-auto block text-center px-8 py-3 rounded-full bg-black/40 text-white font-mono text-xs hover:bg-black/60 transition-colors cursor-pointer hover:scale-105 active:scale-95 duration-200"
            >
              Open Trading Terminal
            </Link>
          </motion.div>
        </motion.div>
      </motion.div>
    </motion.section>
  );
}
