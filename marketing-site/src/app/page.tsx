"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Progress } from "@/components/ui/progress";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import {
  TrendingUp,
  Brain,
  Zap,
  Shield,
  Users,
  BarChart3,
  CheckCircle,
  ArrowRight,
  Star,
  Globe,
  Clock,
  Target,
  Award,
  Play,
  Mail,
  Phone,
  MapPin,
  ArrowUpRight,
  ArrowDownRight,
  Activity,
  Database,
  Settings,
  LineChart as LineChartIcon,
  PieChart as PieChartIcon,
  BarChart as BarChartIcon,
  AreaChart as AreaChartIcon
} from "lucide-react";
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, AreaChart, Area, BarChart as RechartsBarChart, Bar, PieChart as RechartsPieChart, Cell } from "recharts";
import { toast } from "sonner";

// Mock data for charts
const performanceData = [
  { name: 'Jan', accuracy: 85, returns: 12 },
  { name: 'Feb', accuracy: 88, returns: 15 },
  { name: 'Mar', accuracy: 92, returns: 18 },
  { name: 'Apr', accuracy: 89, returns: 14 },
  { name: 'May', accuracy: 94, returns: 22 },
  { name: 'Jun', accuracy: 91, returns: 19 },
];

const modelData = [
  { name: 'XGBoost', accuracy: 92, usage: 35 },
  { name: 'LSTM', accuracy: 89, usage: 25 },
  { name: 'TFT', accuracy: 94, usage: 20 },
  { name: 'LightGBM', accuracy: 90, usage: 15 },
  { name: 'CatBoost', accuracy: 88, usage: 5 },
];

const COLORS = ['#0088FE', '#00C49F', '#FFBB28', '#FF8042', '#8884D8'];

export default function MarketingPage() {
  const [email, setEmail] = useState("");
  const [company, setCompany] = useState("");
  const [interest, setInterest] = useState("");

  const handleDemoRequest = () => {
    if (!email || !company) {
      toast.error("Please fill in all required fields");
      return;
    }
    toast.success("Demo request submitted! We'll contact you within 24 hours.");
    setEmail("");
    setCompany("");
    setInterest("");
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Navigation */}
      <nav className="border-b bg-background/95 backdrop-blur supports-[backdrop-blur]:bg-background/60">
        <div className="container mx-auto px-4 py-4 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Brain className="h-8 w-8 text-primary" />
            <span className="text-xl font-bold">AI Forecasting</span>
          </div>
          <div className="hidden md:flex items-center space-x-6">
            <a href="#features" className="text-sm font-medium hover:text-primary">Features</a>
            <a href="#pricing" className="text-sm font-medium hover:text-primary">Pricing</a>
            <a href="#about" className="text-sm font-medium hover:text-primary">About</a>
            <a href="#contact" className="text-sm font-medium hover:text-primary">Contact</a>
          </div>
          <div className="flex items-center space-x-4">
            <Button variant="outline" size="sm">Sign In</Button>
            <Button size="sm">Get Started</Button>
          </div>
        </div>
      </nav>

      {/* Hero Section */}
      <section className="py-20 px-4">
        <div className="container mx-auto text-center">
          <Badge variant="secondary" className="mb-4">
            <Star className="h-3 w-3 mr-1" />
            Trusted by 500+ Investment Firms
          </Badge>
          <h1 className="text-5xl md:text-6xl font-bold mb-6">
            Transform Your
            <span className="text-primary"> Investment Strategy</span>
            <br />
            with AI-Powered Forecasting
          </h1>
          <p className="text-xl text-muted-foreground mb-8 max-w-3xl mx-auto">
            Leverage advanced machine learning algorithms to predict stock movements with unprecedented accuracy. 
            Get real-time insights, confidence intervals, and actionable recommendations.
          </p>
          <div className="flex flex-col sm:flex-row gap-4 justify-center mb-12">
            <Dialog>
              <DialogTrigger asChild>
                <Button size="lg" className="text-lg px-8">
                  <Play className="h-5 w-5 mr-2" />
                  Watch Demo
                </Button>
              </DialogTrigger>
              <DialogContent className="sm:max-w-md">
                <DialogHeader>
                  <DialogTitle>AI Forecasting Demo</DialogTitle>
                  <DialogDescription>
                    See how our platform transforms investment decision-making
                  </DialogDescription>
                </DialogHeader>
                <div className="aspect-video bg-muted rounded-lg flex items-center justify-center">
                  <Play className="h-16 w-16 text-muted-foreground" />
                </div>
              </DialogContent>
            </Dialog>
            <Button variant="outline" size="lg" className="text-lg px-8">
              <Mail className="h-5 w-5 mr-2" />
              Request Demo
            </Button>
          </div>
          
          {/* Performance Metrics */}
          <div className="grid grid-cols-1 md:grid-cols-4 gap-6 max-w-4xl mx-auto">
            <Card>
              <CardContent className="p-6 text-center">
                <div className="text-3xl font-bold text-primary mb-2">94%</div>
                <div className="text-sm text-muted-foreground">Prediction Accuracy</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6 text-center">
                <div className="text-3xl font-bold text-primary mb-2">320ms</div>
                <div className="text-sm text-muted-foreground">Response Time</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6 text-center">
                <div className="text-3xl font-bold text-primary mb-2">10,000+</div>
                <div className="text-sm text-muted-foreground">Daily Forecasts</div>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-6 text-center">
                <div className="text-3xl font-bold text-primary mb-2">2,677%</div>
                <div className="text-sm text-muted-foreground">Average ROI</div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="py-20 px-4 bg-muted/50">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold mb-4">Why Choose AI Forecasting?</h2>
            <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
              Our platform combines cutting-edge AI with enterprise-grade infrastructure to deliver 
              the most accurate and reliable stock predictions available.
            </p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-8">
            <Card>
              <CardHeader>
                <Brain className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Multi-Model Ensemble</CardTitle>
                <CardDescription>
                  Combines XGBoost, LSTM, TFT, LightGBM, and CatBoost for maximum accuracy
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-sm">XGBoost</span>
                    <Progress value={92} className="w-20" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm">LSTM</span>
                    <Progress value={89} className="w-20" />
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-sm">TFT</span>
                    <Progress value={94} className="w-20" />
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <Zap className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Real-time Processing</CardTitle>
                <CardDescription>
                  Sub-500ms response times for critical investment decisions
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">Single predictions in 320ms</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">Batch processing in 25s</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">100+ concurrent users</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <BarChart3 className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Advanced Analytics</CardTitle>
                <CardDescription>
                  Confidence intervals, feature importance, and performance metrics
                </CardDescription>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={100}>
                  <AreaChart data={performanceData}>
                    <Area type="monotone" dataKey="accuracy" stroke="#8884d8" fill="#8884d8" fillOpacity={0.3} />
                  </AreaChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <Shield className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Enterprise Security</CardTitle>
                <CardDescription>
                  SOC 2 Type II, GDPR, and PCI DSS compliant
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">AES-256 encryption</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">99.5% uptime SLA</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">Role-based access</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <Globe className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Global Coverage</CardTitle>
                <CardDescription>
                  Support for 50+ global markets and exchanges
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">NYSE & NASDAQ</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">London Stock Exchange</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">Tokyo Stock Exchange</span>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <Users className="h-12 w-12 text-primary mb-4" />
                <CardTitle>Dedicated Support</CardTitle>
                <CardDescription>
                  24/7 expert support and custom implementation
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">24/7 technical support</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">Custom model training</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span className="text-sm">White-label solutions</span>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* Performance Section */}
      <section className="py-20 px-4">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold mb-4">Proven Performance</h2>
            <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
              Our platform consistently outperforms traditional methods and delivers measurable results.
            </p>
          </div>
          
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-12 items-center">
            <div>
              <h3 className="text-2xl font-bold mb-6">Accuracy Comparison</h3>
              <div className="space-y-6">
                <div>
                  <div className="flex justify-between mb-2">
                    <span>AI Forecasting</span>
                    <span className="font-bold text-primary">94%</span>
                  </div>
                  <Progress value={94} className="h-3" />
                </div>
                <div>
                  <div className="flex justify-between mb-2">
                    <span>Traditional Methods</span>
                    <span className="font-bold">68%</span>
                  </div>
                  <Progress value={68} className="h-3" />
                </div>
                <div>
                  <div className="flex justify-between mb-2">
                    <span>Market Average</span>
                    <span className="font-bold">52%</span>
                  </div>
                  <Progress value={52} className="h-3" />
                </div>
              </div>
            </div>
            
            <div>
              <ResponsiveContainer width="100%" height={300}>
                <LineChart data={performanceData}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis dataKey="name" />
                  <YAxis />
                  <Tooltip />
                  <Line type="monotone" dataKey="accuracy" stroke="#8884d8" strokeWidth={3} />
                  <Line type="monotone" dataKey="returns" stroke="#82ca9d" strokeWidth={3} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="py-20 px-4 bg-muted/50">
        <div className="container mx-auto">
          <div className="text-center mb-16">
            <h2 className="text-4xl font-bold mb-4">Simple, Transparent Pricing</h2>
            <p className="text-xl text-muted-foreground max-w-2xl mx-auto">
              Choose the plan that fits your needs. All plans include our core forecasting engine.
            </p>
          </div>
          
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8 max-w-5xl mx-auto">
            <Card>
              <CardHeader>
                <CardTitle>Starter</CardTitle>
                <CardDescription>Perfect for small investment firms and individual traders</CardDescription>
                <div className="text-3xl font-bold">$2,500<span className="text-lg text-muted-foreground">/month</span></div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>5,000 predictions/month</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Web dashboard access</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Basic analytics</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Email support</span>
                  </div>
                </div>
                <Button className="w-full">Get Started</Button>
              </CardContent>
            </Card>

            <Card className="border-primary">
              <CardHeader>
                <Badge className="w-fit mb-2">Most Popular</Badge>
                <CardTitle>Professional</CardTitle>
                <CardDescription>Ideal for medium investment firms and wealth managers</CardDescription>
                <div className="text-3xl font-bold">$7,500<span className="text-lg text-muted-foreground">/month</span></div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>25,000 predictions/month</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>API access</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Advanced analytics</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Priority support</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Custom integrations</span>
                  </div>
                </div>
                <Button className="w-full">Get Started</Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Enterprise</CardTitle>
                <CardDescription>For large investment firms, hedge funds, and banks</CardDescription>
                <div className="text-3xl font-bold">$25,000<span className="text-lg text-muted-foreground">/month</span></div>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="space-y-2">
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Unlimited predictions</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Custom models</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>Dedicated support</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>White-label solutions</span>
                  </div>
                  <div className="flex items-center space-x-2">
                    <CheckCircle className="h-4 w-4 text-green-500" />
                    <span>SLA guarantees</span>
                  </div>
                </div>
                <Button className="w-full">Contact Sales</Button>
              </CardContent>
            </Card>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="py-20 px-4">
        <div className="container mx-auto text-center">
          <h2 className="text-4xl font-bold mb-4">Ready to Transform Your Investment Strategy?</h2>
          <p className="text-xl text-muted-foreground mb-8 max-w-2xl mx-auto">
            Join 500+ investment firms already using AI Forecasting to make better decisions.
          </p>
          
          <Card className="max-w-md mx-auto">
            <CardHeader>
              <CardTitle>Request a Demo</CardTitle>
              <CardDescription>
                Get a personalized demonstration of our platform
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label htmlFor="email">Email *</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="your@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="company">Company *</Label>
                <Input
                  id="company"
                  placeholder="Your Company"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="interest">Primary Interest</Label>
                <Select value={interest} onValueChange={setInterest}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select your interest" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="trading">Trading & Execution</SelectItem>
                    <SelectItem value="research">Research & Analytics</SelectItem>
                    <SelectItem value="wealth">Wealth Management</SelectItem>
                    <SelectItem value="risk">Risk Management</SelectItem>
                    <SelectItem value="other">Other</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button onClick={handleDemoRequest} className="w-full">
                Request Demo
                <ArrowRight className="h-4 w-4 ml-2" />
              </Button>
            </CardContent>
          </Card>
        </div>
      </section>

      {/* Footer */}
      <footer className="border-t bg-background">
        <div className="container mx-auto px-4 py-12">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-8">
            <div>
              <div className="flex items-center space-x-2 mb-4">
                <Brain className="h-8 w-8 text-primary" />
                <span className="text-xl font-bold">AI Forecasting</span>
              </div>
              <p className="text-muted-foreground mb-4">
                Transform your investment strategy with AI-powered stock forecasting.
              </p>
              <div className="flex space-x-4">
                <a href="#" className="text-muted-foreground hover:text-primary">
                  <Globe className="h-5 w-5" />
                </a>
                <a href="#" className="text-muted-foreground hover:text-primary">
                  <Mail className="h-5 w-5" />
                </a>
                <a href="#" className="text-muted-foreground hover:text-primary">
                  <Phone className="h-5 w-5" />
                </a>
              </div>
            </div>
            
            <div>
              <h3 className="font-semibold mb-4">Product</h3>
              <div className="space-y-2">
                <a href="#" className="block text-muted-foreground hover:text-primary">Features</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Pricing</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">API</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Documentation</a>
              </div>
            </div>
            
            <div>
              <h3 className="font-semibold mb-4">Company</h3>
              <div className="space-y-2">
                <a href="#" className="block text-muted-foreground hover:text-primary">About</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Blog</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Careers</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Contact</a>
              </div>
            </div>
            
            <div>
              <h3 className="font-semibold mb-4">Support</h3>
              <div className="space-y-2">
                <a href="#" className="block text-muted-foreground hover:text-primary">Help Center</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Status</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Security</a>
                <a href="#" className="block text-muted-foreground hover:text-primary">Privacy</a>
              </div>
            </div>
          </div>
          
          <div className="border-t mt-8 pt-8 text-center text-muted-foreground">
            <p>&copy; 2024 AI Forecasting. All rights reserved.</p>
          </div>
        </div>
      </footer>
    </div>
  );
}
