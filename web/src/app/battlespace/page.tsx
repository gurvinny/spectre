/**
 * RF Battlespace — a live 3D volumetric view of the wireless environment. The
 * WebGL view is dynamically imported with ssr:false (WebGL can't server-render,
 * and this keeps three/fiber/drei out of every other route's bundle).
 * Author: gurvinny
 */
"use client";

import dynamic from "next/dynamic";
import { SectionHeader, Panel, Empty, Pill } from "@/components/ui";

const BattlespaceView = dynamic(
  () => import("@/components/viz3d/BattlespaceView").then((m) => m.BattlespaceView),
  {
    ssr: false,
    loading: () => (
      <Panel>
        <div className="h-[74vh] min-h-[520px] grid place-items-center">
          <Empty>spinning up 3D battlespace…</Empty>
        </div>
      </Panel>
    ),
  },
);

export default function BattlespacePage() {
  return (
    <div className="flex flex-col gap-4 max-w-[1600px] mx-auto">
      <SectionHeader
        index="◈ 3D"
        title="RF Battlespace"
        sub="volumetric situational awareness"
        right={<Pill color="var(--color-phosphor)">experimental</Pill>}
      />
      <BattlespaceView />
    </div>
  );
}
