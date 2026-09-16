import React from 'react';
import { Agent, AgentId } from '@/types';
import { ORSO_AGENTS } from '@/lib/data';

interface AgentSelectorProps {
  activeAgentId: AgentId;
  onSelectAgent: (agentId: AgentId) => void;
}

export const AgentSelector: React.FC<AgentSelectorProps> = ({
  activeAgentId,
  onSelectAgent,
}) => {
  return (
    <div className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-none">
      {ORSO_AGENTS.map((agent: Agent) => {
        const isActive = agent.id === activeAgentId;
        return (
          <button
            key={agent.id}
            onClick={() => onSelectAgent(agent.id)}
            className={`flex items-center gap-2.5 px-3.5 py-2 rounded-xl text-left transition-all border shrink-0 ${
              isActive
                ? `${agent.themeColor.bg} ${agent.themeColor.border} ring-1 ring-white/10 shadow-lg`
                : 'bg-slate-900/60 border-slate-800/80 text-slate-400 hover:text-slate-200 hover:bg-slate-850 hover:border-slate-700'
            }`}
          >
            <div className="relative">
              <span className="text-xl leading-none select-none">{agent.avatar}</span>
              <span
                className={`absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full ring-2 ring-slate-950 ${
                  agent.status === 'online' ? 'bg-emerald-400' : 'bg-amber-400'
                }`}
              />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className={`text-sm font-semibold truncate ${isActive ? 'text-white' : 'text-slate-300'}`}>
                  {agent.name}
                </span>
                {isActive && (
                  <span className={`text-[10px] px-1.5 py-0.2 rounded font-medium border ${agent.themeColor.badge}`}>
                    Actif
                  </span>
                )}
              </div>
              <p className="text-[11px] text-slate-400 truncate max-w-[140px]">
                {agent.department}
              </p>
            </div>
          </button>
        );
      })}
    </div>
  );
};
