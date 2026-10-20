import { Card, CardContent, CardHeader } from '@/components/ui/card';

/** A dashboard card whose title is an h2 (CardTitle is an h3, which would skip a level under the page h1). */
export function DashboardCard({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <h2 className="font-semibold leading-none tracking-tight">{title}</h2>
        {description && <p className="text-sm text-muted-foreground">{description}</p>}
      </CardHeader>
      <CardContent>{children}</CardContent>
    </Card>
  );
}
