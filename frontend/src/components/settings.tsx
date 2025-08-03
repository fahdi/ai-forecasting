"use client";

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Settings as SettingsIcon, Shield, Database, Bell } from "lucide-react";

export function Settings() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-bold">Settings</h1>
        <p className="text-muted-foreground">Configure system preferences</p>
      </div>
      
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>API Configuration</CardTitle>
            <CardDescription>Manage API keys and endpoints</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span>API Key</span>
                <Button size="sm" variant="outline">Configure</Button>
              </div>
              <div className="flex justify-between items-center">
                <span>Rate Limiting</span>
                <span className="text-sm text-muted-foreground">1000 req/hour</span>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Data Sources</CardTitle>
            <CardDescription>Configure data providers</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span>Yahoo Finance</span>
                <Button size="sm" variant="outline">Configure</Button>
              </div>
              <div className="flex justify-between items-center">
                <span>Alpha Vantage</span>
                <Button size="sm" variant="outline">Configure</Button>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Notifications</CardTitle>
            <CardDescription>Manage alerts and updates</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span>Email Alerts</span>
                <Button size="sm" variant="outline">Configure</Button>
              </div>
              <div className="flex justify-between items-center">
                <span>Model Training</span>
                <span className="text-sm text-muted-foreground">Enabled</span>
              </div>
            </div>
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>System</CardTitle>
            <CardDescription>System preferences and maintenance</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <span>Auto Updates</span>
                <span className="text-sm text-muted-foreground">Enabled</span>
              </div>
              <div className="flex justify-between items-center">
                <span>Backup</span>
                <Button size="sm" variant="outline">Configure</Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
} 