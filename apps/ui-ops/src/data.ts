import { AgentId, AgentMeta } from "./types";

export const AGENTS_CATALOG: Record<AgentId, AgentMeta> = {
  jerome: {
    id: "jerome",
    name: "Jérôme",
    role: "Recouvrement & Trésorerie",
    avatar: "blue",
    color: "from-blue-500 to-indigo-600",
    badgeBg: "bg-blue-500/10 border-blue-500/30 text-blue-400",
    badgeText: "Credit Manager",
    description: "Analyse les balances âgées, détecte les retards et prépare les relances amiables.",
  },
  lucas: {
    id: "lucas",
    name: "Lucas",
    role: "Commercial & Prospection",
    avatar: "purple",
    color: "from-purple-500 to-pink-600",
    badgeBg: "bg-purple-500/10 border-purple-500/30 text-purple-400",
    badgeText: "SDR & Vente",
    description: "Qualifie les leads, suit les devis et relance les opportunités d'affaires.",
  },
  clara: {
    id: "clara",
    name: "Clara",
    role: "Support & Relation Client",
    avatar: "emerald",
    color: "from-emerald-500 to-teal-600",
    badgeBg: "bg-emerald-500/10 border-emerald-500/30 text-emerald-400",
    badgeText: "SAV & Litiges",
    description: "Prend en charge les réclamations, litiges et questions récurrentes 24/7.",
  },
  victor: {
    id: "victor",
    name: "Victor",
    role: "Veille & Marchés Publics",
    avatar: "amber",
    color: "from-amber-500 to-orange-600",
    badgeBg: "bg-amber-500/10 border-amber-500/30 text-amber-400",
    badgeText: "AO & BOAMP",
    description: "Surveille les appels d'offres (BOAMP) et assiste au montage des dossiers DCE.",
  },
};
