"use client";

import { Circle } from "lucide-react";
import {
  Card,
  CardGroup,
  CardHeader,
  CardTitle,
  CardDescription,
  CardFooter,
  CardMedia,
  CardButton,
} from "@/components/ui/card";
import { useIcons, type IconName } from "@/lib/icon-context";
import { cn } from "@/lib/utils";

export interface CardSectionItem {
  id: string;
  name: string;
  description?: string;
  icon?: any;
}

// Seed content for the generated card group — replace with your own.
const SEED_ITEMS: CardSectionItem[] = [
  { id: "fluid-motion", icon: "circle", name: "Fluid motion", description: "Spring-tuned transitions calibrated across three tiers" },
  { id: "accessible-default", icon: "shield", name: "Accessible by default", description: "Focus-visible rings and ARIA roles in every part" },
  { id: "themeable", icon: "palette", name: "Yours to theme", description: "Swap radius, icons, and primitive at runtime" },
  { id: "dark-mode", icon: "moon", name: "Dark mode ready", description: "Tokens adapt to light and dark automatically" },
];

export interface CardSectionProps {
  items?: CardSectionItem[];
  selectedModel?: string;
  onSelectModel?: (id: string) => void;
  disabled?: boolean;
  className?: string;
}

export function CardSection({
  items,
  selectedModel,
  onSelectModel,
  disabled = false,
  className,
}: CardSectionProps = {}) {
  const icons = useIcons();
  const displayItems = items && items.length > 0 ? items : SEED_ITEMS;

  return (
    <div
      className={cn(
        "w-full rounded-lg border border-border/60 bg-muted/10 overflow-hidden",
        className
      )}
    >
      <CardGroup orientation="inline">
        {displayItems.map((item) => {
          const isSelected = selectedModel === item.id;
          const iconComponent =
            typeof item.icon === "string"
              ? icons[item.icon as IconName] || Circle
              : item.icon || Circle;

          return (
            <Card
              key={item.id}
              onClick={() => !disabled && onSelectModel?.(item.id)}
              selected={isSelected}
              disabled={disabled}
              label={item.name}
            >
              <CardMedia icon={iconComponent} />
              <CardHeader>
                <CardTitle>{item.name}</CardTitle>
                <CardDescription>{item.description || item.id}</CardDescription>
              </CardHeader>
              <CardFooter>
                <CardButton
                  variant={isSelected ? "primary" : "secondary"}
                  onClick={(e: React.MouseEvent) => {
                    e.stopPropagation();
                    if (!disabled) onSelectModel?.(item.id);
                  }}
                >
                  {isSelected ? "Connected" : "Connect"}
                </CardButton>
              </CardFooter>
            </Card>
          );
        })}
      </CardGroup>
    </div>
  );
}
