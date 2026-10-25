/**
 * LiveKit side of starting a call: how many calls are live, and a token for a new one.
 *
 * The room name and the agent dispatch are decided here, never taken from the browser: a
 * visitor can't pick a room (to join someone else's call) or dispatch a different agent.
 */
import {
  AccessToken,
  RoomAgentDispatch,
  RoomConfiguration,
  RoomServiceClient,
} from 'livekit-server-sdk';
import { nanoid } from 'nanoid';

export type LiveKitConfig = { url: string; apiKey: string; apiSecret: string; agentName: string };

/** Every active room in the project uses one of LiveKit's concurrent sessions (web or phone). */
export async function liveCalls(lk: LiveKitConfig): Promise<number> {
  const rooms = await new RoomServiceClient(lk.url, lk.apiKey, lk.apiSecret).listRooms();
  return rooms.length;
}

export async function callToken(lk: LiveKitConfig): Promise<string> {
  const at = new AccessToken(lk.apiKey, lk.apiSecret, {
    identity: `visitor-${nanoid(10)}`,
    name: 'Caller',
    // Only needs to last until the browser joins; LiveKit refreshes it after that. Short, so a
    // copied token can't be replayed later to start a call that skipped the checks.
    ttl: '2m',
  });
  at.addGrant({
    room: `kestrel-web-${nanoid(12)}`, // a fresh room for every call
    roomJoin: true,
    canPublish: true,
    canSubscribe: true,
    canPublishData: true, // the page sends its greeting timing to the agent as a text stream
  });
  // Explicit dispatch: the agent registers as "riley" and only joins rooms that ask for it.
  at.roomConfig = new RoomConfiguration({
    agents: [new RoomAgentDispatch({ agentName: lk.agentName })],
  });
  return at.toJwt();
}
