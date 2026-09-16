import React from 'react';
import { Agent } from '@/types';
import { Sparkles } from 'lucide-react';

interface QuickActionsProps {
  agent: Agent;
  onTriggerPrompt: (prompt: string) => void;
  disabled?: boolean;
}

export const QuickActions: React.FC<QuickActionsProps> = ({
  agent,
  onTriggerPrompt,
  disabled = false,
}) => {
  return (
    <div className="flex items-center gap-2 overflow-x-auto py-2 scrollbar-none">
      <div className="flex items-center gap-1 text-xs text-slate-500 shrink-0 font-medium pl-1">
        <Sparkles className="w-3.5 h-3.5 text-blue-400" />
        <span>Actions rapides :</span>
      </div>
      {agent.quickActions.map((qa, index) => (
        <button
          key={index}
          onClick={() => onTriggerPrompt(qa.prompt)}
          disabled={disabled}
          className="px-3 py-1.5 rounded-full text-xs font-medium bg-slate-900/90 hover:bg-slate-800 border border-slate-800 hover:border-slate-700 text-slate-300 hover:text-white transition-all shrink-0 active:scale-95 disabled:opacity-50 disabled:pointer-events-none shadow-sm"
        >
          {qa.label}
        </button>
      ))}
    </div>
  );
};
