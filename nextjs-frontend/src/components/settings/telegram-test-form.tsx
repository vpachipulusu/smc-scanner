'use client';

import { useActionState } from 'react';

import { sendTestMessageAction } from '@/app/settings/actions';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { IDLE_ROW_STATE } from '@/lib/automation/state';

/** Chat id field plus the test button. Results are announced in a live region; fixed messages only. */
export function TelegramTestForm({ configured }: { configured: boolean }) {
  const [state, formAction, pending] = useActionState(sendTestMessageAction, IDLE_ROW_STATE);

  return (
    <form action={formAction} className="space-y-3">
      <div className="space-y-2">
        <Label htmlFor="telegram-chat-id">Chat id (optional)</Label>
        <Input
          id="telegram-chat-id"
          name="chat_id"
          autoComplete="off"
          maxLength={40}
          placeholder="-1001234567890 or @channelname"
          aria-describedby="telegram-chat-help"
        />
        <p id="telegram-chat-help" className="text-sm text-muted-foreground">
          Leave empty to use the server&apos;s default chat.
        </p>
      </div>
      <Button type="submit" variant="outline" disabled={!configured || pending}>
        {pending ? 'Sending…' : 'Send test message'}
      </Button>
      {!configured && (
        <p className="text-sm text-muted-foreground">
          Disabled: Telegram is not configured on the server.
        </p>
      )}
      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className={
          state.status === 'error'
            ? 'text-sm text-crit-foreground'
            : 'text-sm text-muted-foreground'
        }
      >
        {state.status !== 'idle' && !pending && (
          <>
            {state.status === 'error' && <strong>Error: </strong>}
            {state.message}
          </>
        )}
      </div>
    </form>
  );
}
