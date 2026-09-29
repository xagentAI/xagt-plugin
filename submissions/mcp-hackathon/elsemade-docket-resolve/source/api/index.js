import { deploymentConfig } from "../src/config.js";
import { createRequestHandler } from "../src/http.js";

export default createRequestHandler(deploymentConfig());
