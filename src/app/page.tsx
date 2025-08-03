"use client";

import { useState } from "react";
import { Sidebar } from "@/components/sidebar";
import { Dashboard } from "@/components/dashboard";
import { Forecasts } from "@/components/forecasts";
import { Models } from "@/components/models";
import { Data } from "@/components/data";
import { Analytics } from "@/components/analytics";
import { Settings } from "@/components/settings";

type TabType = "dashboard" | "forecasts" | "models" | "data" | "analytics" | "settings";

export default function Home() {
  const [activeTab, setActiveTab] = useState<TabType>("dashboard");

  const renderContent = () => {
    switch (activeTab) {
      case "dashboard":
        return <Dashboard />;
      case "forecasts":
        return <Forecasts />;
      case "models":
        return <Models />;
      case "data":
        return <Data />;
      case "analytics":
        return <Analytics />;
      case "settings":
        return <Settings />;
      default:
        return <Dashboard />;
    }
  };

  return (
    <div className="flex h-screen bg-background">
      <Sidebar activeTab={activeTab} setActiveTab={setActiveTab} />
      <main className="flex-1 overflow-auto">
        <div className="container mx-auto p-6">
          {renderContent()}
        </div>
      </main>
    </div>
  );
} 