/**
 * TypeScript types representing the Supabase database schema.
 * Generated manually — run `npx supabase gen types` in production
 * to keep this in sync with your actual schema.
 */
export type Json =
  | string
  | number
  | boolean
  | null
  | { [key: string]: Json | undefined }
  | Json[];

export type LaunchpadId =
  | "meteora"
  | "bags"
  | "pumpfun"
  | "fourmeme"
  | "pons"
  | "sherwood";
export type LaunchStatus = "pending" | "confirming" | "live" | "failed";
export type TokenStatus = "active" | "pending" | "failed";
export type ChainNetwork = "devnet" | "testnet" | "mainnet-beta" | "bsc" | "base" | "robinhood";
export type AppPhase = "testnet" | "mainnet";

export interface Database {
  public: {
    Tables: {
      users: {
        Row: {
          id: string;
          wallet_address: string;
          session_version: number;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          wallet_address: string;
          session_version?: number;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          wallet_address?: string;
          session_version?: number;
          updated_at?: string;
        };
        Relationships: [];
      };

      tokens: {
        Row: {
          id: string;
          user_id: string;
          wallet_address: string;
          name: string;
          symbol: string;
          decimals: number;
          supply: string;
          description: string | null;
          image_url: string | null;
          network: ChainNetwork;
          app_phase: AppPhase;
          mint_address: string | null;
          mint_tx: string | null;
          status: TokenStatus;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          user_id: string;
          wallet_address: string;
          name: string;
          symbol: string;
          decimals?: number;
          supply: string;
          description?: string | null;
          image_url?: string | null;
          network?: ChainNetwork;
          app_phase?: AppPhase;
          mint_address?: string | null;
          mint_tx?: string | null;
          status?: TokenStatus;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          name?: string;
          symbol?: string;
          decimals?: number;
          supply?: string;
          description?: string | null;
          image_url?: string | null;
          network?: ChainNetwork;
          app_phase?: AppPhase;
          mint_address?: string | null;
          mint_tx?: string | null;
          status?: TokenStatus;
          updated_at?: string;
        };
        Relationships: [
          {
            foreignKeyName: "tokens_user_id_fkey";
            columns: ["user_id"];
            isOneToOne: false;
            referencedRelation: "users";
            referencedColumns: ["id"];
          },
        ];
      };

      launches: {
        Row: {
          id: string;
          token_id: string;
          user_id: string;
          wallet_address: string;
          launchpad: LaunchpadId;
          network: ChainNetwork;
          app_phase: AppPhase;
          status: LaunchStatus;
          pool_address: string | null;
          launch_tx: string | null;
          initial_liquidity: number | null;
          volume_24h: number | null;
          launched_at: string | null;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          token_id: string;
          user_id: string;
          wallet_address: string;
          launchpad: LaunchpadId;
          network?: ChainNetwork;
          app_phase?: AppPhase;
          status?: LaunchStatus;
          pool_address?: string | null;
          launch_tx?: string | null;
          initial_liquidity?: number | null;
          volume_24h?: number | null;
          launched_at?: string | null;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          status?: LaunchStatus;
          network?: ChainNetwork;
          app_phase?: AppPhase;
          pool_address?: string | null;
          launch_tx?: string | null;
          initial_liquidity?: number | null;
          volume_24h?: number | null;
          launched_at?: string | null;
          updated_at?: string;
        };
        Relationships: [
          {
            foreignKeyName: "launches_token_id_fkey";
            columns: ["token_id"];
            isOneToOne: false;
            referencedRelation: "tokens";
            referencedColumns: ["id"];
          },
          {
            foreignKeyName: "launches_user_id_fkey";
            columns: ["user_id"];
            isOneToOne: false;
            referencedRelation: "users";
            referencedColumns: ["id"];
          },
        ];
      };

      earnings: {
        Row: {
          id: string;
          user_id: string;
          wallet_address: string;
          token_id: string;
          launch_id: string;
          launchpad: LaunchpadId;
          network: ChainNetwork;
          app_phase: AppPhase;
          amount_sol: number;
          fee_type: string;
          tx_signature: string | null;
          recorded_at: string;
          created_at: string;
        };
        Insert: {
          id?: string;
          user_id: string;
          wallet_address: string;
          token_id: string;
          launch_id: string;
          launchpad: LaunchpadId;
          network?: ChainNetwork;
          app_phase?: AppPhase;
          amount_sol: number;
          fee_type?: string;
          tx_signature?: string | null;
          recorded_at?: string;
          created_at?: string;
        };
        Update: {
          network?: ChainNetwork;
          app_phase?: AppPhase;
          amount_sol?: number;
          tx_signature?: string | null;
        };
        Relationships: [
          {
            foreignKeyName: "earnings_token_id_fkey";
            columns: ["token_id"];
            isOneToOne: false;
            referencedRelation: "tokens";
            referencedColumns: ["id"];
          },
          {
            foreignKeyName: "earnings_launch_id_fkey";
            columns: ["launch_id"];
            isOneToOne: false;
            referencedRelation: "launches";
            referencedColumns: ["id"];
          },
          {
            foreignKeyName: "earnings_user_id_fkey";
            columns: ["user_id"];
            isOneToOne: false;
            referencedRelation: "users";
            referencedColumns: ["id"];
          },
        ];
      };
      admin_settings: {
        Row: {
          key: string;
          value: Json;
          updated_by_wallet: string | null;
          updated_at: string;
        };
        Insert: {
          key: string;
          value?: Json;
          updated_by_wallet?: string | null;
          updated_at?: string;
        };
        Update: {
          value?: Json;
          updated_by_wallet?: string | null;
          updated_at?: string;
        };
        Relationships: [];
      };
      admin_audit_logs: {
        Row: {
          id: string;
          wallet_address: string;
          action: string;
          payload: Json;
          created_at: string;
        };
        Insert: {
          id?: string;
          wallet_address: string;
          action: string;
          payload?: Json;
          created_at?: string;
        };
        Update: {
          payload?: Json;
        };
        Relationships: [];
      };
      developer_api_keys: {
        Row: {
          id: string;
          user_id: string;
          wallet_address: string;
          name: string;
          api_key: string;
          created_at: string;
          revoked: boolean;
        };
        Insert: {
          id?: string;
          user_id: string;
          wallet_address: string;
          name: string;
          api_key: string;
          created_at?: string;
          revoked?: boolean;
        };
        Update: {
          name?: string;
          revoked?: boolean;
        };
        Relationships: [
          {
            foreignKeyName: "developer_api_keys_user_id_fkey";
            columns: ["user_id"];
            isOneToOne: false;
            referencedRelation: "users";
            referencedColumns: ["id"];
          }
        ];
      };
      developer_wallets: {
        Row: {
          id: string;
          user_id: string;
          wallet_address: string;
          network: string;
          public_key: string;
          encrypted_private_key: string;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          user_id: string;
          wallet_address: string;
          network: string;
          public_key: string;
          encrypted_private_key: string;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          public_key?: string;
          encrypted_private_key?: string;
          updated_at?: string;
        };
        Relationships: [
          {
            foreignKeyName: "developer_wallets_user_id_fkey";
            columns: ["user_id"];
            isOneToOne: false;
            referencedRelation: "users";
            referencedColumns: ["id"];
          }
        ];
      };
      trading_agents: {
        Row: {
          id: string;
          user_id: string | null;
          wallet_address: string;
          name: string;
          description: string | null;
          prompt: string;
          mode: "paper" | "live";
          status: "active" | "paused" | "completed" | "failed";
          chain: string;
          launchpads: string[];
          strategy_config: Json;
          budget_allocated: number;
          budget_spent: number;
          total_pnl_pct: number;
          total_trades: number;
          successful_trades: number;
          created_at: string;
          updated_at: string;
        };
        Insert: {
          id?: string;
          user_id?: string | null;
          wallet_address: string;
          name: string;
          description?: string | null;
          prompt: string;
          mode?: "paper" | "live";
          status?: "active" | "paused" | "completed" | "failed";
          chain?: string;
          launchpads?: string[];
          strategy_config?: Json;
          budget_allocated?: number;
          budget_spent?: number;
          total_pnl_pct?: number;
          total_trades?: number;
          successful_trades?: number;
          created_at?: string;
          updated_at?: string;
        };
        Update: {
          name?: string;
          description?: string | null;
          mode?: "paper" | "live";
          status?: "active" | "paused" | "completed" | "failed";
          chain?: string;
          launchpads?: string[];
          strategy_config?: Json;
          budget_allocated?: number;
          budget_spent?: number;
          total_pnl_pct?: number;
          total_trades?: number;
          successful_trades?: number;
          updated_at?: string;
        };
        Relationships: [
          {
            foreignKeyName: "trading_agents_user_id_fkey";
            columns: ["user_id"];
            isOneToOne: false;
            referencedRelation: "users";
            referencedColumns: ["id"];
          }
        ];
      };
      agent_trades: {
        Row: {
          id: string;
          agent_id: string | null;
          token_symbol: string;
          token_mint: string | null;
          action: string;
          launchpad: string;
          chain: string;
          amount_in: number;
          amount_out: number;
          pnl_pct: number | null;
          pnl_sol: number | null;
          tx_signature: string | null;
          mode: "paper" | "live";
          execution_log: string | null;
          created_at: string;
        };
        Insert: {
          id?: string;
          agent_id?: string | null;
          token_symbol: string;
          token_mint?: string | null;
          action: string;
          launchpad: string;
          chain?: string;
          amount_in: number;
          amount_out: number;
          pnl_pct?: number | null;
          pnl_sol?: number | null;
          tx_signature?: string | null;
          mode?: "paper" | "live";
          execution_log?: string | null;
          created_at?: string;
        };
        Update: {
          token_symbol?: string;
          token_mint?: string | null;
          action?: string;
          launchpad?: string;
          chain?: string;
          amount_in?: number;
          amount_out?: number;
          pnl_pct?: number | null;
          pnl_sol?: number | null;
          tx_signature?: string | null;
          mode?: "paper" | "live";
          execution_log?: string | null;
        };
        Relationships: [
          {
            foreignKeyName: "agent_trades_agent_id_fkey";
            columns: ["agent_id"];
            isOneToOne: false;
            referencedRelation: "trading_agents";
            referencedColumns: ["id"];
          }
        ];
      };

      treasury_transfers: {
        Row: {
          id: string;
          chain: string;
          from_wallet: string;
          to_wallet: string;
          amount_native: number;
          amount_lamports: number | null;
          signature: string | null;
          fee_type: string;
          status: string;
          reason: string | null;
          error_message: string | null;
          created_at: string;
          confirmed_at: string | null;
        };
        Insert: {
          id?: string;
          chain: string;
          from_wallet: string;
          to_wallet: string;
          amount_native: number;
          amount_lamports?: number | null;
          signature?: string | null;
          fee_type: string;
          status?: string;
          reason?: string | null;
          error_message?: string | null;
          created_at?: string;
          confirmed_at?: string | null;
        };
        Update: {
          id?: string;
          chain?: string;
          from_wallet?: string;
          to_wallet?: string;
          amount_native?: number;
          amount_lamports?: number | null;
          signature?: string | null;
          fee_type?: string;
          status?: string;
          reason?: string | null;
          error_message?: string | null;
          created_at?: string;
          confirmed_at?: string | null;
        };
        Relationships: [];
      };
    };
    Views: Record<string, never>;
    Functions: Record<string, never>;
    Enums: {
      launchpad_id: LaunchpadId;
      launch_status: LaunchStatus;
      token_status: TokenStatus;
      chain_network: ChainNetwork;
      app_phase: AppPhase;
    };
    CompositeTypes: Record<string, never>;
  };
}

// Convenience type aliases
export type User = Database["public"]["Tables"]["users"]["Row"];
export type Token = Database["public"]["Tables"]["tokens"]["Row"];
export type Launch = Database["public"]["Tables"]["launches"]["Row"];
export type Earning = Database["public"]["Tables"]["earnings"]["Row"];
export type DeveloperApiKey = Database["public"]["Tables"]["developer_api_keys"]["Row"];
export type DeveloperWallet = Database["public"]["Tables"]["developer_wallets"]["Row"];
export type DBTradingAgent = Database["public"]["Tables"]["trading_agents"]["Row"];
export type DBAgentTrade = Database["public"]["Tables"]["agent_trades"]["Row"];

export type TokenInsert = Database["public"]["Tables"]["tokens"]["Insert"];
export type LaunchInsert = Database["public"]["Tables"]["launches"]["Insert"];
export type EarningInsert = Database["public"]["Tables"]["earnings"]["Insert"];
export type DeveloperApiKeyInsert = Database["public"]["Tables"]["developer_api_keys"]["Insert"];
export type DeveloperWalletInsert = Database["public"]["Tables"]["developer_wallets"]["Insert"];
export type DBTradingAgentInsert = Database["public"]["Tables"]["trading_agents"]["Insert"];
export type DBAgentTradeInsert = Database["public"]["Tables"]["agent_trades"]["Insert"];

