import { describe, it, expect, beforeEach } from 'vitest';
import { SessionInfoService } from '@/services/session-info-service';

describe('SessionInfoService with SQLite', () => {
  let service: SessionInfoService;

  beforeEach(async () => {
    SessionInfoService.resetInstance();
    service = new SessionInfoService(':memory:');
    await service.initialize();
  });

  it('should create and retrieve session info', async () => {
    const info = await service.getSessionInfo('sess1');
    expect(info.custom_name).toBe('');
    await service.updateCustomName('sess1', 'Test');
    const updated = await service.getSessionInfo('sess1');
    expect(updated.custom_name).toBe('Test');
  });

  it('should update session fields', async () => {
    await service.updateSessionInfo('sess2', { pinned: true });
    const info = await service.getSessionInfo('sess2');
    expect(info.pinned).toBe(true);
  });

  it('should delete session', async () => {
    await service.updateSessionInfo('sess3', { custom_name: 'Del' });
    await service.deleteSession('sess3');
    const all = await service.getAllSessionInfo();
    expect(all['sess3']).toBeUndefined();
  });

  it('should return all sessions', async () => {
    await service.updateSessionInfo('a', { custom_name: 'A' });
    await service.updateSessionInfo('b', { custom_name: 'B' });
    const all = await service.getAllSessionInfo();
    expect(Object.keys(all).sort()).toEqual(['a', 'b']);
  });

  it('should archive all sessions', async () => {
    await service.updateSessionInfo('a', { custom_name: 'A' });
    await service.updateSessionInfo('b', { custom_name: 'B' });
    const count = await service.archiveAllSessions();
    expect(count).toBe(2);
    const all = await service.getAllSessionInfo();
    expect(all['a'].archived).toBe(true);
    expect(all['b'].archived).toBe(true);
  });

  it('should sync missing sessions', async () => {
    const inserted = await service.syncMissingSessions(['x', 'y']);
    expect(inserted).toBe(2);
    const all = await service.getAllSessionInfo();
    expect(Object.keys(all).sort()).toEqual(['x', 'y']);
  });

  it('should provide stats', async () => {
    await service.updateSessionInfo('s', { custom_name: 'S' });
    const stats = await service.getStats();
    expect(stats.sessionCount).toBe(1);
    expect(stats.lastUpdated).toBeTypeOf('string');
  });

  // Phase 1E: session_type tests
  describe('session_type support', () => {
    it('should default session_type to user', async () => {
      const info = await service.getSessionInfo('new-sess');
      expect(info.session_type).toBe('user');
    });

    it('should update session_type via updateSessionType', async () => {
      await service.getSessionInfo('agent-sess');
      await service.updateSessionType('agent-sess', 'agent');
      const info = await service.getSessionInfo('agent-sess');
      expect(info.session_type).toBe('agent');
    });

    it('should preserve session_type across updates', async () => {
      await service.updateSessionInfo('typed-sess', { session_type: 'agent' });
      await service.updateSessionInfo('typed-sess', { custom_name: 'My Agent' });
      const info = await service.getSessionInfo('typed-sess');
      expect(info.session_type).toBe('agent');
      expect(info.custom_name).toBe('My Agent');
    });

    it('should include session_type in getAllSessionInfo', async () => {
      await service.updateSessionInfo('user1', { session_type: 'user' });
      await service.updateSessionInfo('agent1', { session_type: 'agent' });
      const all = await service.getAllSessionInfo();
      expect(all['user1'].session_type).toBe('user');
      expect(all['agent1'].session_type).toBe('agent');
    });
  });

  // Phase 1E: batch delete tests
  describe('batchDeleteSessions', () => {
    it('should delete multiple sessions atomically', async () => {
      await service.updateSessionInfo('a', { custom_name: 'A' });
      await service.updateSessionInfo('b', { custom_name: 'B' });
      await service.updateSessionInfo('c', { custom_name: 'C' });

      const deletedCount = await service.batchDeleteSessions(['a', 'b']);
      expect(deletedCount).toBe(2);

      const all = await service.getAllSessionInfo();
      expect(Object.keys(all)).toEqual(['c']);
    });

    it('should return 0 for non-existent sessions', async () => {
      const deletedCount = await service.batchDeleteSessions(['nonexistent1', 'nonexistent2']);
      expect(deletedCount).toBe(0);
    });

    it('should handle empty array', async () => {
      const deletedCount = await service.batchDeleteSessions([]);
      expect(deletedCount).toBe(0);
    });

    it('should handle mix of existing and non-existing', async () => {
      await service.updateSessionInfo('exists', { custom_name: 'E' });
      const deletedCount = await service.batchDeleteSessions(['exists', 'not-exists']);
      expect(deletedCount).toBe(1);
    });
  });
});

