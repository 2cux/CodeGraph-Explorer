import { Module } from "@nestjs/common";
import { UsersController } from "./users.controller";
import { UsersService } from "./users.service";

const dynamicProvider = { provide: "DYNAMIC", useFactory: () => ({}) };

@Module({
  controllers: [UsersController],
  providers: [UsersService, dynamicProvider],
})
export class UsersModule {}
