import { AgentId, ActionCardData, ChatMessage } from '@/types';

export function getTenantSlug(): string | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem('orso_client_user');
    if (!raw) return null;
    const user = JSON.parse(raw);
    return user?.tenant?.tenant_slug || user?.tenant_slug || null;
  } catch {
    return null;
  }
}

export function getApiBaseUrl(): string {
  if (typeof window === 'undefined') return '';
  const hostname = window.location.hostname;
  const tenantSlug = getTenantSlug();
  const tenantPrefix = tenantSlug ? `/t/${tenantSlug}` : '';

  if (import.meta.env.VITE_API_BASE_URL) {
    return `${import.meta.env.VITE_API_BASE_URL}${tenantPrefix}`;
  }

  // Sur l'instance dédiée, l'Ingress unifié (app.orso-agents.fr), Docker ou local
  if (
    hostname === 'app.orso-agents.fr' ||
    hostname === 'prod-fr-002.orso-agents.fr' ||
    hostname === 'localhost' ||
    hostname === '127.0.0.1'
  ) {
    return tenantPrefix;
  }

  // Si l'UI tourne sur le site vitrine externe ou preview Vercel
  if (hostname.endsWith('orso-agents.fr') || hostname.endsWith('vercel.app')) {
    return `https://app.orso-agents.fr${tenantPrefix}`;
  }

  return tenantPrefix;
}

export function getWebSocketUrl(): string {
  if (typeof window === 'undefined') return '';
  const slug = getTenantSlug();
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const host = window.location.host || 'localhost:9119';
  if (slug) {
    return `${proto}//${host}/t/${slug}/ws`;
  }
  return `${proto}//${host}/ws`;
}

export async function wakeTenantEnvironment(tenantSlug?: string): Promise<{ success: boolean; message?: string }> {
  const slug = tenantSlug || getTenantSlug();
  if (!slug) return { success: false, message: 'Aucun identifiant d’organisation trouvé.' };
  try {
    const res = await fetch(`/api/olympe/tenants/wake/${slug}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    });
    const data = await res.json();
    return { success: res.ok, message: data.message };
  } catch (err: any) {
    return { success: false, message: err?.message || 'Superviseur Olympe injoignable.' };
  }
}

// ── Gestion des Tokens & Authentification Client ────────────────────────────

const TOKEN_STORAGE_KEY = 'orso_client_token';
const USER_STORAGE_KEY = 'orso_client_user';

export function getClientToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem(TOKEN_STORAGE_KEY) || sessionStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setClientToken(token: string, remember: boolean = true): void {
  if (typeof window === 'undefined') return;
  if (remember) {
    localStorage.setItem(TOKEN_STORAGE_KEY, token);
  } else {
    sessionStorage.setItem(TOKEN_STORAGE_KEY, token);
  }
}

export function clearClientToken(): void {
  if (typeof window === 'undefined') return;
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  sessionStorage.removeItem(TOKEN_STORAGE_KEY);
  localStorage.removeItem(USER_STORAGE_KEY);
}

export function getStoredUser(): any | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = localStorage.getItem(USER_STORAGE_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setStoredUser(user: any): void {
  if (typeof window === 'undefined') return;
  localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user));
}

export function getAuthHeaders(): Record<string, string> {
  const token = getClientToken();
  if (token) {
    return {
      'Authorization': `Bearer ${token}`,
    };
  }
  return {};
}

export async function loginClient(email: string, password: string): Promise<{
  success: boolean;
  user?: any;
  tenant?: any;
  token?: string;
  target_environment?: any;
  redirect_url?: string;
  error?: string;
}> {
  const base = getApiBaseUrl();
  try {
    const res = await fetch(`${base}/api/client/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ email, password }),
    });

    const data = await res.json();
    if (!res.ok) {
      return {
        success: false,
        error: data.detail || 'Échec de la connexion.',
      };
    }

    if (data.access_token) {
      setClientToken(data.access_token);
      setStoredUser({
        ...data.user,
        tenant: data.tenant,
        target_environment: data.target_environment,
      });
      return {
        success: true,
        user: data.user,
        tenant: data.tenant,
        token: data.access_token,
        target_environment: data.target_environment,
        redirect_url: data.redirect_url,
      };
    }
  } catch (err: any) {
    return {
      success: false,
      error: `Erreur réseau : ${err?.message || err}`,
    };
  }
  return { success: false, error: 'Réponse inattendue du serveur.' };
}

export async function logoutClient(): Promise<void> {
  const base = getApiBaseUrl();
  try {
    await fetch(`${base}/api/client/auth/logout`, { method: 'POST' });
  } catch {}
  clearClientToken();
}

export async function checkSessionMe(): Promise<{
  authenticated: boolean;
  user?: any;
  tenant?: any;
}> {
  const token = getClientToken();
  if (!token) return { authenticated: false };

  const base = getApiBaseUrl();
  try {
    const res = await fetch(`${base}/api/client/auth/me`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        ...getAuthHeaders(),
      },
    });
    if (res.ok) {
      const data = await res.json();
      return {
        authenticated: true,
        user: data.user,
        tenant: data.tenant,
      };
    }
    if (res.status === 401 || res.status === 403) {
      clearClientToken();
    }
  } catch {}
  return { authenticated: false };
}

// Detect if we have a live backend and real LLM connectivity
export async function checkBackendHealth(): Promise<{ online: boolean; llmConnected?: boolean; version?: string }> {
  const base = getApiBaseUrl();
  try {
    const res = await fetch(`${base}/api/client/status`, { method: 'GET', headers: { accept: 'application/json' } });
    if (res.ok) {
      const data = await res.json();
      return {
        online: true,
        llmConnected: Boolean(data?.llm_connected),
        version: data?.version || '1.0.0',
      };
    }
  } catch {
    // try fallback /api/status
    try {
      const fallback = await fetch(`${base}/api/status`, { method: 'GET', headers: { accept: 'application/json' } });
      if (fallback.ok) {
        return { online: true, llmConnected: false };
      }
    } catch {
      // offline
    }
  }
  return { online: false, llmConnected: false };
}

// Generate an initial welcome message for the selected agent
export function getAgentWelcomeMessage(agentId: AgentId): ChatMessage {
  const timestamp = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  switch (agentId) {
    case 'jerome':
      return {
        id: 'welcome-jerome',
        agentId: 'jerome',
        role: 'assistant',
        content: `Bonjour ! Je suis **Jérôme**, votre assistant dédié au recouvrement et à la protection de votre trésorerie.\n\nJ'ai analysé vos factures ce matin : **3 factures** présentent un retard de paiement supérieur à 15 jours pour un montant total de **8 420 €**.\n\nQue souhaitez-vous faire aujourd'hui ?`,
        timestamp,
        actionCard: {
          id: 'action-sample-1',
          agentId: 'jerome',
          title: 'Proposition de relance amiable (Niveau 1)',
          type: 'invoice_reminder',
          recipientName: 'SARL Bâtiment Moderne',
          recipientContact: 'comptabilite@batiment-moderne.fr',
          amount: 4520.00,
          dueDate: '15 Août 2026',
          invoiceNumber: 'FAC-2026-089',
          channel: 'email',
          draftSubject: 'Rappel amical : Facture FAC-2026-089 en attente de règlement',
          draftContent: `Bonjour,\n\nSauf erreur de notre part, nous constatons que la facture FAC-2026-089 d'un montant de 4 520,00 € TTC arrivée à échéance le 15/08/2026 demeure à ce jour impayée.\n\nPourriez-vous nous confirmer la programmation de son règlement ou nous transmettre l'ordre de virement ?\n\nBien cordialement,\nLe service comptabilité`,
          status: 'pending',
        },
      };
    case 'lucas':
      return {
        id: 'welcome-lucas',
        agentId: 'lucas',
        role: 'assistant',
        content: `Bonjour ! Je suis **Lucas**, votre commercial et chasseur d'opportunités.\n\nJ'ai pré-qualifié **4 nouveaux prospects** dans votre zone géographique cible qui recrutent activement et correspondent à votre offre.\n\nSouhaitez-vous que je vous présente la liste ou que je prépare les e-mails d'approche personnalisés ?`,
        timestamp,
      };
    case 'clara':
      return {
        id: 'welcome-clara',
        agentId: 'clara',
        role: 'assistant',
        content: `Bonjour ! Je suis **Clara**, votre responsable support client et SAV.\n\nTous les tickets de la matinée ont reçu une première réponse. Aucun incident majeur n'est signalé sur vos services.\n\nComment puis-je vous aider ?`,
        timestamp,
      };
    case 'victor':
      return {
        id: 'welcome-victor',
        agentId: 'victor',
        role: 'assistant',
        content: `Bonjour ! Je suis **Victor**, votre veilleur marchés publics.\n\nLe BOAMP a publié **2 consultations publiques** très pertinentes ce matin dans votre domaine d'activité en région Hauts-de-France.\n\nSouhaitez-vous consulter les fiches de synthèse des critères de sélection ?`,
        timestamp,
      };
  }
}

// Send user prompt to agent via real backend SSE stream with fallback
export async function sendUserPrompt(
  agentId: AgentId,
  prompt: string,
  onDelta?: (text: string) => void,
  sessionId?: string
): Promise<ChatMessage> {
  const timestamp = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });

  // 1. Tenter le streaming direct via le backend FastAPI /api/client/chat
  try {
    const base = getApiBaseUrl();
    const response = await fetch(`${base}/api/client/chat`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'text/event-stream',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        agent_id: agentId,
        message: prompt,
        session_id: sessionId || `client-session-${Date.now()}`,
      }),
    });

    if (!response.ok) {
      console.error(`Erreur HTTP backend /api/client/chat: ${response.status} ${response.statusText}`);
      const errText = await response.text().catch(() => '');
      console.error('Corps de l\'erreur backend:', errText);
    } else if (response.body) {
      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let accumulatedContent = '';
      let receivedCard: ActionCardData | undefined = undefined;
      let buffer = '';

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || '';

        let currentEvent = 'message';
        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;

          if (trimmed.startsWith('event:')) {
            currentEvent = trimmed.slice(6).trim();
          } else if (trimmed.startsWith('data:')) {
            const rawData = trimmed.slice(5).trim();
            try {
              const parsed = JSON.parse(rawData);
              if (currentEvent === 'delta' && parsed.content) {
                accumulatedContent += parsed.content;
                if (onDelta) {
                  onDelta(accumulatedContent);
                }
              } else if (currentEvent === 'action_card') {
                receivedCard = parsed as ActionCardData;
              } else if (currentEvent === 'done' && parsed.full_text) {
                accumulatedContent = parsed.full_text;
              }
            } catch {
              // Ignore SSE JSON parse error on partial chunks
            }
          }
        }
      }

      if (accumulatedContent.trim()) {
        return {
          id: `msg-${Date.now()}`,
          agentId,
          role: 'assistant',
          content: accumulatedContent,
          timestamp,
          actionCard: receivedCard,
        };
      }
    }
  } catch (err) {
    console.warn("Connexion backend SSE indisponible, bascule sur simulation locale:", err);
  }

  // 2. Mode de repli intelligent (simulation hors-ligne / démo)
  const normalized = prompt.toLowerCase();
  let responseText = "";
  let actionCard: ActionCardData | undefined = undefined;

  if (agentId === 'jerome') {
    if (normalized.includes('balance') || normalized.includes('retard') || normalized.includes('trésorerie') || normalized.includes('impayé')) {
      responseText = `Voici la synthèse actualisée de votre **balance âgée** au ${new Date().toLocaleDateString('fr-FR')} :\n\n` +
        `• **Non échues (à venir)** : 48 250 € (18 factures)\n` +
        `• **Retard 1 à 15 jours** : 4 520 € (1 facture — SARL Bâtiment Moderne)\n` +
        `• **Retard 16 à 30 jours** : 3 900 € (1 facture — Société Dupont Peinture)\n` +
        `• **Retard > 30 jours** : 0 € (Excellente maîtrise du risque global)\n\n` +
        `💡 **Ma recommandation :** Nous devrions valider la relance pour la société **Dupont Peinture** avant la fin de journée. J'ai préparé la carte d'action ci-dessous pour votre arbitrage en 1 clic :`;

      actionCard = {
        id: `action-${Date.now()}`,
        agentId: 'jerome',
        title: 'Relance ferme recommandée (Niveau 2)',
        type: 'invoice_reminder',
        recipientName: 'Société Dupont Peinture',
        recipientContact: 'j.dupont@peinture-nord.fr',
        amount: 3900.00,
        dueDate: '10 Juillet 2026',
        invoiceNumber: 'FAC-2026-072',
        channel: 'email',
        draftSubject: '2ème Relance : Retard important facture FAC-2026-072',
        draftContent: `Monsieur Dupont,\n\nMalgré notre première relance amicale, la facture FAC-2026-072 d'un montant de 3 900,00 € TTC présente désormais un retard de plus de 45 jours.\n\nNous vous demandons de bien vouloir régulariser cette créance sous 48 heures ou nous contacter afin de convenir d'un échéancier immédiat.\n\nRestant à votre écoute,\nLa Direction`,
        status: 'pending',
      };
    } else if (normalized.includes('siren') || normalized.includes('pappers') || normalized.includes('santé')) {
      responseText = `J'ai interrogé l'API Pappers et le BODACC sur le SIREN demandé :\n\n` +
        `• **Dénomination** : SAS ATELIER DU NORD\n` +
        `• **Score de solvabilité** : 🟢 **82/100 (Faible risque)**\n` +
        `• **Chiffre d'affaires déclaré** : 1 240 000 € (Résultat net : +48 000 €)\n` +
        `• **Procédures collectives / BODACC** : Aucune mention négative relevée.\n` +
        `• **Conseil crédit** : Vous pouvez lui accorder des délais de paiement standards à 30 jours nets dans la limite d'un encours de 15 000 €.`;
    } else {
      responseText = `Je travaille pour vous ! J'ai bien noté votre demande : « *${prompt}* ».\n\n` +
        `Je viens de vérifier les données comptables correspondantes dans Pennylane. Tout est en ordre. Si vous souhaitez que j'envoie une relance ou que j'ajuste un encours client, dites-le-moi simplement !`;
    }
  } else if (agentId === 'lucas') {
    responseText = `J'ai analysé votre demande commerciale. Voici les éléments clés :\n\n` +
      `1. **Ciblage validé** : Entreprises de 10 à 50 salariés ayant renouvelé leurs équipements récemment.\n` +
      `2. **Points d'entrée identifiés** : Directeurs des Opérations et Gérants.\n` +
      `3. **Prochaine étape** : J'ai préparé la fiche prospect dans HubSpot avec les coordonnées vérifiées.`;
  } else if (agentId === 'clara') {
    responseText = `Bien reçu ! J'ai consulté l'historique des interactions avec ce client. Toutes ses questions précédentes portaient sur les délais de livraison. Je lui ai apporté une réponse claire et personnalisée.`;
  } else {
    responseText = `Analyse effectuée. Le dossier de consultation présente un taux d'adéquation de 85% avec votre offre. Les pièces administratives exigées (DC1, DC2, attestation d'assurance) sont prêtes.`;
  }

  // Progressive streaming simulation
  if (onDelta) {
    const words = responseText.split(" ");
    let accumulated = "";
    for (let i = 0; i < words.length; i++) {
      accumulated += (i > 0 ? " " : "") + words[i];
      onDelta(accumulated);
      await new Promise((r) => setTimeout(r, 15));
    }
  }

  return {
    id: `msg-${Date.now()}`,
    agentId,
    role: 'assistant',
    content: responseText,
    timestamp,
    actionCard,
  };
}

// Execute 1-Click interactive action via backend
export async function executeClientAction(
  actionId: string,
  cardId: string,
  agentId: AgentId = 'jerome',
  draft?: string,
  recipient?: string
): Promise<{ success: boolean; message: string; timestamp?: string }> {
  try {
    const base = getApiBaseUrl();
    const res = await fetch(`${base}/api/client/actions/execute`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
      },
      body: JSON.stringify({
        action_id: actionId,
        card_id: cardId,
        agent_id: agentId,
        draft,
        recipient,
      }),
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn("Backend action execute unavailable, using local response:", err);
  }

  const now = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  if (actionId === 'send') {
    return { success: true, message: `Relance envoyée avec succès à ${recipient || 'le destinataire'} (${now})` };
  } else if (actionId === 'delay') {
    return { success: true, message: `Relance reportée de 7 jours (${now})` };
  }
  return { success: true, message: `Action prise en compte (${now})` };
}
