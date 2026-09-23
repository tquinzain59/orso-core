import React from "react";
import { LayoutDashboard, Users, CreditCard, Server, RefreshCw, ShieldCheck, LogOut, User } from "lucide-react";
import { AdminUser } from "../types";

interface NavbarProps {
  activeTab: "dashboard" | "tenants" | "billing" | "fleet";
  setActiveTab: (tab: "dashboard" | "tenants" | "billing" | "fleet") => void;
  onRefresh: () => void;
  loading: boolean;
  totalClients: number;
  adminUser?: AdminUser | null;
  onLogout?: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  activeTab,
  setActiveTab,
  onRefresh,
  loading,
  totalClients,
  adminUser,
  onLogout,
}) => {
  return (
    <header className="sticky top-0 z-40 bg-slate-900/80 backdrop-blur-md border-b border-slate-800">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Brand */}
          <div className="flex items-center space-x-3">
            <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-sky-500 to-indigo-600 flex items-center justify-center shadow-lg shadow-sky-500/20">
              <ShieldCheck className="w-6 h-6 text-white" />
            </div>
            <div>
              <div className="flex items-center space-x-2">
                <span className="font-bold text-lg text-white tracking-tight">ORSO OPS</span>
                <span className="text-xs px-2 py-0.5 rounded-full font-medium bg-sky-500/10 text-sky-400 border border-sky-500/20">
                  Cockpit
                </span>
              </div>
              <p className="text-xs text-slate-400">Orchestrateur Olympe & Flotte Multi-Tenant</p>
            </div>
          </div>

          {/* Nav Tabs */}
          <nav className="flex items-center space-x-1 sm:space-x-2">
            <button
              onClick={() => setActiveTab("dashboard")}
              className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                activeTab === "dashboard"
                  ? "bg-slate-800 text-sky-400 shadow-sm border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <LayoutDashboard className="w-4 h-4" />
              <span>Vue d'ensemble</span>
            </button>

            <button
              onClick={() => setActiveTab("tenants")}
              className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                activeTab === "tenants"
                  ? "bg-slate-800 text-sky-400 shadow-sm border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Users className="w-4 h-4" />
              <span>Clients</span>
              {totalClients > 0 && (
                <span className="ml-1.5 px-1.5 py-0.2 rounded-full text-xs bg-slate-700 text-slate-300">
                  {totalClients}
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab("billing")}
              className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                activeTab === "billing"
                  ? "bg-slate-800 text-sky-400 shadow-sm border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <CreditCard className="w-4 h-4" />
              <span>Facturation & Forfaits</span>
            </button>

            <button
              onClick={() => setActiveTab("fleet")}
              className={`flex items-center space-x-2 px-3 py-2 rounded-lg text-sm font-medium transition-all cursor-pointer ${
                activeTab === "fleet"
                  ? "bg-slate-800 text-sky-400 shadow-sm border border-slate-700"
                  : "text-slate-400 hover:text-slate-200 hover:bg-slate-800/50"
              }`}
            >
              <Server className="w-4 h-4" />
              <span>Flotte Olympe</span>
            </button>
          </nav>

          {/* User info, Refresh & Logout */}
          <div className="flex items-center space-x-3">
            <div className="hidden lg:flex items-center space-x-2 px-2.5 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-medium">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
              <span>Olympe: 9230</span>
            </div>

            <button
              onClick={onRefresh}
              disabled={loading}
              className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 border border-transparent hover:border-slate-700 transition-all disabled:opacity-50 cursor-pointer"
              title="Rafraîchir les données"
            >
              <RefreshCw className={`w-4 h-4 ${loading ? "animate-spin text-sky-400" : ""}`} />
            </button>

            {adminUser && (
              <div className="flex items-center space-x-2 pl-2 border-l border-slate-800">
                <div className="hidden sm:flex flex-col items-end text-right">
                  <span className="text-xs font-medium text-slate-200 truncate max-w-[140px]">
                    {adminUser.full_name || adminUser.email}
                  </span>
                  <span className="text-[10px] text-sky-400 font-semibold uppercase tracking-wider">
                    {adminUser.role}
                  </span>
                </div>
                <div className="w-8 h-8 rounded-full bg-sky-500/20 border border-sky-500/30 flex items-center justify-center text-sky-400 font-bold text-xs">
                  <User className="w-4 h-4" />
                </div>
                {onLogout && (
                  <button
                    onClick={onLogout}
                    className="p-2 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-rose-500/10 border border-transparent hover:border-rose-500/20 transition-all cursor-pointer"
                    title="Déconnexion"
                  >
                    <LogOut className="w-4 h-4" />
                  </button>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </header>
  );
};
