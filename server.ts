import express from 'express';
import { randomUUID } from 'node:crypto';
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StreamableHTTPServerTransport } from '@modelcontextprotocol/sdk/server/streamableHttp.js';
import { z } from 'zod';
// import { ResourceTemplate } from '@modelcontextprotocol/sdk/server/mcp.js';

// Create an Express application
const app = express();
app.use(express.json());

// Create an MCP server with name and version
const server = new McpServer(
  { name: "Example MCP Server", version: "1.0.0" },
  { 
    capabilities: { 
      // Enable capabilities for tools, resources, and logging
      tools: { listChanged: true },
      resources: { listChanged: true },
      logging: {}
    },
    instructions: "This server provides weather forecasts, notes management, and calculator tools."
  }
);

// Map to store active transports
const transports: Record<string, StreamableHTTPServerTransport> = {};

// Register a simple calculator tool
server.tool(
  "calculator",
  "A simple calculator that can perform basic arithmetic operations",
  {
    operation: z.enum(["add", "subtract", "multiply", "divide"]),
    a: z.number().describe("First operand"),
    b: z.number().describe("Second operand")
  },
  async ({ operation, a, b }) => {
    let result;
    switch (operation) {
      case "add": result = a + b; break;
      case "subtract": result = a - b; break;
      case "multiply": result = a * b; break;
      case "divide": 
        if (b === 0) {
          return {
            content: [{ type: "text", text: "Error: Division by zero" }],
            isError: true
          };
        }
        result = a / b; 
        break;
    }
    return {
      content: [{ type: "text", text: `Result: ${result}` }]
    };
  }
);

// Register a weather forecast tool
server.tool(
  "weather-forecast",
  "Get weather forecast for a location",
  {
    location: z.string().describe("City name or location"),
    days: z.number().min(1).max(7).default(1).describe("Number of days to forecast (1-7)")
  },
  async ({ location, days }, { sendNotification }) => {
    // Simulate API call delay
    await new Promise(resolve => setTimeout(resolve, 500));
    
    // Send a notification to demonstrate communication during tool execution
    await sendNotification({
      method: "notifications/message",
      params: { level: "info", data: `Retrieving weather forecast for ${location} for ${days} day(s)...` }
    });

    // Simulate different weather conditions
    const conditions = ["Sunny", "Cloudy", "Rainy", "Partly Cloudy", "Stormy"];
    let forecast = `Weather forecast for ${location}:\n\n`;
    
    for (let i = 0; i < days; i++) {
      const randomCondition = conditions[Math.floor(Math.random() * conditions.length)];
      const randomTemp = Math.floor(Math.random() * 30) + 10; // Random temperature 10-40°C
      forecast += `Day ${i+1}: ${randomCondition}, ${randomTemp}°C\n`;
    }
    
    return {
      content: [{ type: "text", text: forecast }]
    };
  }
);

// Register a notes manager tool
const notes = new Map();

server.tool(
  "notes-manager",
  "Create and retrieve notes",
  {
    action: z.enum(["create", "list", "get", "delete"]),
    id: z.string().optional(),
    content: z.string().optional()
  },
  async ({ action, id, content }) => {
    switch (action) {
      case "create":
        if (!content) {
          return {
            content: [{ type: "text", text: "Error: Content is required for create action" }],
            isError: true
          };
        }
        const noteId = id || randomUUID();
        notes.set(noteId, content);
        return {
          content: [{ type: "text", text: `Note created with ID: ${noteId}` }]
        };
        
      case "list":
        if (notes.size === 0) {
          return {
            content: [{ type: "text", text: "No notes found" }]
          };
        }
        let notesList = "Notes:\n\n";
        notes.forEach((value, key) => {
          notesList += `- ${key}: ${value.substring(0, 30)}${value.length > 30 ? '...' : ''}\n`;
        });
        return {
          content: [{ type: "text", text: notesList }]
        };
        
      case "get":
        if (!id) {
          return {
            content: [{ type: "text", text: "Error: Note ID is required for get action" }],
            isError: true
          };
        }
        if (!notes.has(id)) {
          return {
            content: [{ type: "text", text: `Error: Note with ID ${id} not found` }],
            isError: true
          };
        }
        return {
          content: [{ type: "text", text: notes.get(id) }]
        };
        
      case "delete":
        if (!id) {
          return {
            content: [{ type: "text", text: "Error: Note ID is required for delete action" }],
            isError: true
          };
        }
        if (!notes.has(id)) {
          return {
            content: [{ type: "text", text: `Error: Note with ID ${id} not found` }],
            isError: true
          };
        }
        notes.delete(id);
        return {
          content: [{ type: "text", text: `Note ${id} deleted successfully` }]
        };
    }
  }
);

// Register a static resource
server.resource(
  "server-info",
  "info://server",
  { 
    description: "Information about this MCP server",
    mimeType: "text/plain" 
  },
  async () => ({
    contents: [
      {
        uri: "info://server",
        text: `Server: Example MCP Server v1.0.0
Description: This server demonstrates simple tools and resources with the MCP protocol.
Tools available: calculator, weather-forecast, notes-manager
Resources available: WIP
`
      }
    ]
  })
);


// Handle requests with error handling
app.post('/mcp', async (req, res) => {
  try {
    // Check for existing session ID
    const sessionId = req.headers['mcp-session-id'] as string | undefined;
    let transport: StreamableHTTPServerTransport;

    if (sessionId && transports[sessionId]) {
      // Reuse existing transport
      transport = transports[sessionId];
    } else if (!sessionId && req.body && req.body.method === 'initialize') {
      // New initialization request
      transport = new StreamableHTTPServerTransport({
        sessionIdGenerator: () => randomUUID(),
        onsessioninitialized: (sessionId) => {
          console.log(`Session initialized with ID: ${sessionId}`);
          transports[sessionId] = transport;
        }
      });

      // Set up onclose handler to clean up transport when closed
      transport.onclose = () => {
        if (transport.sessionId) {
          console.log(`Transport closed for session ${transport.sessionId}`);
          delete transports[transport.sessionId];
        }
      };

      // Connect the transport to the MCP server
      await server.connect(transport);
    } else {
      // Invalid request
      res.status(400).json({
        jsonrpc: "2.0",
        error: {
          code: -32000,
          message: "Bad Request: No valid session ID provided"
        },
        id: null
      });
      return;
    }

    // Handle the request
    await transport.handleRequest(req, res);
  } catch (error) {
    console.error('Error handling request:', error);
    if (!res.headersSent) {
      res.status(500).json({
        jsonrpc: "2.0",
        error: {
          code: -32603,
          message: "Internal server error"
        },
        id: null
      });
    }
  }
});

// Handle GET requests for SSE streams
app.get('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'] as string | undefined;
  if (!sessionId || !transports[sessionId]) {
    res.status(400).send('Invalid or missing session ID');
    return;
  }

  try {
    await transports[sessionId].handleRequest(req, res);
  } catch (error) {
    console.error('Error handling SSE request:', error);
    if (!res.headersSent) {
      res.status(500).send('Error establishing SSE stream');
    }
  }
});

// Handle DELETE requests for session termination
app.delete('/mcp', async (req, res) => {
  const sessionId = req.headers['mcp-session-id'] as string | undefined;
  if (!sessionId || !transports[sessionId]) {
    res.status(400).send('Invalid or missing session ID');
    return;
  }

  try {
    console.log(`Received session termination request for session ${sessionId}`);
    await transports[sessionId].handleRequest(req, res);
  } catch (error) {
    console.error('Error handling session termination:', error);
    if (!res.headersSent) {
      res.status(500).send('Error processing session termination');
    }
  }
});

/* Send capability change events to console for debugging
server.onCapabilityChange((event) => {
  if (event.action === "invoked") {
    console.log(`${event.capabilityType} '${event.capabilityName}' invoked`);
  } else if (event.action === "completed") {
    console.log(`${event.capabilityType} '${event.capabilityName}' completed in ${event.durationMs}ms`);
  } else if (event.action === "error") {
    console.error(`${event.capabilityType} '${event.capabilityName}' error: ${event.error}`);
  }
});
*/

// Start the server
const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`MCP Streamable HTTP Server running on port ${PORT}`);
  // console.log(`Server info: ${server.server.version().name} ${server.server.getVersion().version}`);
  // console.log(`Capabilities: ${Object.keys(server.server.getCapabilities()).join(', ')}`);
});

// Handle graceful shutdown
process.on('SIGINT', async () => {
  console.log('\nShutting down server...');
  
  // Close all transports
  for (const sessionId in transports) {
    try {
      await transports[sessionId].close();
    } catch (error) {
      console.error(`Error closing transport for session ${sessionId}:`, error);
    }
  }
  
  // Close the server
  await server.close();
  console.log('Server shut down gracefully');
  process.exit(0);
});

