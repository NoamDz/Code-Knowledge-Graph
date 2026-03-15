const express = require("express");
const { validateToken, refreshToken } = require("./auth");
const UserModel = require("../models/user");
const logger = require("../utils/logger");

class UserController {
  constructor(userService) {
    this.userService = userService;
    this.router = express.Router();
    this._bindRoutes();
  }

  _bindRoutes() {
    this.router.get("/users/:id", this.getUser.bind(this));
    this.router.post("/users", this.createUser.bind(this));
    this.router.put("/users/:id", this.updateUser.bind(this));
  }

  async getUser(req, res) {
    try {
      const user = await this.userService.findById(req.params.id);
      if (!user) {
        return res.status(404).json({ error: "User not found" });
      }
      res.json(user);
    } catch (err) {
      logger.error("Failed to get user", err);
      res.status(500).json({ error: "Internal error" });
    }
  }

  async createUser(req, res) {
    const validated = validateToken(req.headers.authorization);
    if (!validated) {
      return res.status(401).json({ error: "Unauthorized" });
    }

    const user = await this.userService.create(req.body);
    logger.info(`User created: ${user.id}`);
    res.status(201).json(user);
  }

  async updateUser(req, res) {
    const user = await this.userService.update(req.params.id, req.body);
    res.json(user);
  }
}

const createRouter = (userService) => {
  const controller = new UserController(userService);
  return controller.router;
};

module.exports = { UserController, createRouter };
