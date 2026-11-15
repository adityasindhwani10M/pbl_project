// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title LandChainIndiaRegistry
 * @notice Decentralized Land Title Registration & Ownership Mutation Smart Contract
 */
contract LandChainIndiaRegistry {
    struct Property {
        string upin;
        string currentOwner;
        string location;
        string category;
        string area;
        string documentHash;
        uint256 registeredAt;
        bool exists;
    }

    struct OwnershipTransfer {
        string upin;
        string fromOwner;
        string toOwner;
        string instrument;
        uint256 timestamp;
    }

    mapping(string => Property) private properties;
    mapping(string => OwnershipTransfer[]) private transferHistory;

    event PropertyMinted(
        string indexed upin,
        string owner,
        string documentHash,
        uint256 timestamp
    );

    event OwnershipTransferred(
        string indexed upin,
        string previousOwner,
        string newOwner,
        uint256 timestamp
    );

    function registerProperty(
        string memory _upin,
        string memory _owner,
        string memory _location,
        string memory _category,
        string memory _area,
        string memory _documentHash
    ) public {
        require(!properties[_upin].exists, "UPIN already registered on blockchain");

        properties[_upin] = Property({
            upin: _upin,
            currentOwner: _owner,
            location: _location,
            category: _category,
            area: _area,
            documentHash: _documentHash,
            registeredAt: block.timestamp,
            exists: true
        });

        emit PropertyMinted(_upin, _owner, _documentHash, block.timestamp);
    }

    function transferProperty(
        string memory _upin,
        string memory _currentOwner,
        string memory _newOwner,
        string memory _instrument
    ) public {
        require(properties[_upin].exists, "UPIN not registered");
        require(
            keccak256(bytes(properties[_upin].currentOwner)) == keccak256(bytes(_currentOwner)),
            "Seller does not match current legal owner"
        );

        properties[_upin].currentOwner = _newOwner;

        transferHistory[_upin].push(
            OwnershipTransfer({
                upin: _upin,
                fromOwner: _currentOwner,
                toOwner: _newOwner,
                instrument: _instrument,
                timestamp: block.timestamp
            })
        );

        emit OwnershipTransferred(_upin, _currentOwner, _newOwner, block.timestamp);
    }

    function getProperty(string memory _upin) public view returns (Property memory) {
        require(properties[_upin].exists, "UPIN not found");
        return properties[_upin];
    }
}