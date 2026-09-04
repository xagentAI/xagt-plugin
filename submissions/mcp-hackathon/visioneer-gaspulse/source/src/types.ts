export interface GasBucket {
  periodStart: string;
  periodEnd: string;
  txCount: number;
  gasUsed: string;
  avgGasPriceGwei: number;
}

export interface GasTrend {
  totalGasUsed: string;
  avgGasPriceGwei: number;
  direction: "increasing" | "decreasing" | "flat" | "insufficient_data";
  buckets: GasBucket[];
}

export interface ActivityScore {
  value: number;
  recency: number;
  frequency: number;
  consistency: number;
}

export interface ActivityResponse {
  address: string;
  network: "ethereum-mainnet";
  windowDays: number;
  asOf: string;
  txCount: number;
  firstSeen: string | null;
  lastSeen: string | null;
  gasTrend: GasTrend;
  activityScore: ActivityScore;
  dataSource: "etherscan";
}

export interface GasOracleResponse {
  network: "ethereum-mainnet";
  asOf: string;
  safeGwei: number;
  standardGwei: number;
  fastGwei: number;
  dataSource: "etherscan";
}

export interface EtherscanTx {
  hash: string;
  timeStamp: string;
  gas: string;
  gasPrice: string;
  gasUsed: string;
  isError: string;
}

export interface ApiError {
  error: {
    code: string;
    message: string;
  };
}
